"""Recursive-descent Cypher/GQL parser (tokens -> IR)."""

from __future__ import annotations

import typing as t
from collections.abc import Iterator
from contextlib import contextmanager

from cypherast import ast as a
from cypherast.errors import ParseError, Position
from cypherast.lexer import Lexer, Token, TokenKind

# Mirrors CPython's default ``sys.getrecursionlimit()``. Nesting beyond this
# raises ParseError CG1105 instead of an uncatchable interpreter crash.
MAX_PARSE_DEPTH = 1000


class _ParseDepthExceeded(Exception):
    """Internal signal: nesting guard tripped.

    Not a ``ParseError`` so the parser's speculative ``except ParseError``
    backtracking cannot swallow it; ``parse`` converts it to CG1105.
    """


class Parser:
    """Handwritten recursive-descent parser for openCypher core (+ Neo4j/GQL tolerant bits)."""

    def __init__(
        self,
        source: str,
        dialect: str | None = None,
        max_depth: int = MAX_PARSE_DEPTH,
    ) -> None:
        self.source = source
        self.dialect = dialect
        self.max_depth = max_depth
        self.tokens = Lexer(source).tokenize()
        self._i = 0
        self._depth = 0

    # --- public -----------------------------------------------------------

    def parse(self) -> a.AstNode:
        try:
            return self._parse_root()
        except (_ParseDepthExceeded, RecursionError) as exc:
            # One nesting level costs several Python frames, so the interpreter
            # limit can trip before ``max_depth``; report the same diagnostic.
            raise self._depth_error() from exc

    def _parse_root(self) -> a.AstNode:
        version = None
        if self._match(TokenKind.CYPHER) and self._check(TokenKind.INTEGER):
            version = int(self._advance().text)
        node = self.parse_statement()
        if not self._check(TokenKind.EOF):
            tok = self._peek()
            raise self._err(
                f"Unexpected token {tok.text!r}",
                code="CG1101",
                expected={"EOF"},
            )
        return a.Cypher(this=node, version=version)

    def parse_statement(self) -> a.AstNode:
        with self._nesting():
            if self._check(TokenKind.WHEN) and self._dialect_allows("allow_when_query"):
                return self.parse_when_query()
            left: a.AstNode = self.parse_query()
            while self._match(TokenKind.UNION):
                distinct = not self._match(TokenKind.ALL)
                right = self.parse_query()
                left = a.Union(this=left, expression=right, distinct=distinct)
            # GQL NEXT chaining (parse-tolerant)
            while self._match(TokenKind.NEXT):
                right = self.parse_query()
                left = a.Next(this=left, expression=right)
            return left

    def parse_query(self) -> a.Query:
        clauses: list[a.AstNode] = []
        if self._match(TokenKind.USE):
            clauses.append(a.Use(graph=self.parse_expression()))
        while True:
            if (
                self._check_word("LOAD")
                and self._check_word("CSV", 1)
                and self._dialect_allows("allow_load_csv")
            ):
                clauses.append(self.parse_load_csv())
            elif self._check(TokenKind.FILTER) and self._dialect_allows("allow_filter_clause"):
                clauses.append(self.parse_filter())
            elif self._check(TokenKind.LET) and self._dialect_allows("allow_let_clause"):
                clauses.append(self.parse_let())
            elif self._check(TokenKind.FOR) and self._dialect_allows("allow_for_clause"):
                clauses.append(self.parse_for())
            elif self._dialect_allows("allow_admin_ddl") and (
                self._check_word("SHOW")
                or (
                    self._check(TokenKind.CREATE)
                    and self._peek_ahead_text(1) in ("INDEX", "CONSTRAINT")
                )
            ):
                clauses.append(self.parse_admin_statement())
                break
            elif self._check(TokenKind.CALL) or (
                self._check(TokenKind.OPTIONAL) and self._check_ahead(TokenKind.CALL)
            ):
                clauses.append(self.parse_call())
            elif self._check(TokenKind.OPTIONAL) or self._check(TokenKind.MATCH):
                clauses.append(self.parse_match())
            elif self._check(TokenKind.UNWIND):
                clauses.append(self.parse_unwind())
            elif self._check(TokenKind.WITH):
                clauses.append(self.parse_with())
            elif self._check(TokenKind.CREATE):
                clauses.append(self.parse_create())
            elif self._check(TokenKind.MERGE):
                clauses.append(self.parse_merge())
            elif self._check(TokenKind.SET):
                clauses.append(self.parse_set())
            elif self._check(TokenKind.DELETE) or self._check(TokenKind.DETACH):
                clauses.append(self.parse_delete())
            elif self._check(TokenKind.REMOVE):
                clauses.append(self.parse_remove())
            elif self._check(TokenKind.FOREACH):
                clauses.append(self.parse_foreach())
            elif self._check(TokenKind.INSERT):
                clauses.append(self.parse_insert())
            elif self._check(TokenKind.RETURN):
                clauses.append(self.parse_return())
                break
            elif self._check(TokenKind.FINISH):
                self._advance()
                break
            else:
                break
        if not clauses:
            raise self._err("Expected a query clause", code="CG1103")
        return a.Query(clauses=clauses)

    # --- clauses ----------------------------------------------------------

    def parse_match(self) -> a.Match:
        optional = self._match(TokenKind.OPTIONAL)
        self._expect(TokenKind.MATCH)
        pattern = self.parse_pattern()
        search = None
        if self._check_word("SEARCH") and self._dialect_allows("allow_search_clause"):
            search = self.parse_search()
        where = None
        if self._match(TokenKind.WHERE):
            where = a.Where(this=self.parse_expression())
        hints = self._parse_match_hints()
        return a.Match(
            pattern=pattern,
            optional=optional or None,
            where=where,
            hints=hints,
            search=search,
        )

    def _parse_match_hints(self) -> list[str] | None:
        hints: list[str] = []
        while self._match(TokenKind.USING):
            parts = ["USING"]
            if self._match(TokenKind.INDEX):
                parts.append("INDEX")
            elif self._match(TokenKind.SCAN):
                parts.append("SCAN")
            elif self._match(TokenKind.JOIN):
                parts.append("JOIN")
            else:
                raise self._err(
                    "Expected INDEX, SCAN, or JOIN after USING",
                    code="CG1102",
                    expected={"INDEX", "SCAN", "JOIN"},
                )
            while self._check(TokenKind.IDENT) or self._check(TokenKind.COLON):
                parts.append(self._advance().text)
                if self._check(TokenKind.LPAREN):
                    parts.append(self._advance().text)
                    while not self._check(TokenKind.RPAREN) and not self._check(TokenKind.EOF):
                        parts.append(self._advance().text)
                    if self._check(TokenKind.RPAREN):
                        parts.append(self._advance().text)
            hints.append(" ".join(parts))
        return hints or None

    def parse_unwind(self) -> a.Unwind:
        self._expect(TokenKind.UNWIND)
        expr = self.parse_expression()
        self._expect(TokenKind.AS)
        alias = self.parse_variable()
        return a.Unwind(expression=expr, alias=alias)

    def parse_with(self) -> a.With:
        self._expect(TokenKind.WITH)
        distinct = self._match(TokenKind.DISTINCT)
        exprs = self.parse_return_items()
        # GROUP BY precedes the ORDER BY / SKIP / LIMIT tail (Cypher 25 clause order).
        group_by = self._parse_group_by()
        order = self.parse_order_by() if self._check(TokenKind.ORDER) else None
        skip = a.Skip(this=self.parse_expression()) if self._match(TokenKind.SKIP) else None
        limit = a.Limit(this=self.parse_expression()) if self._match(TokenKind.LIMIT) else None
        where = a.Where(this=self.parse_expression()) if self._match(TokenKind.WHERE) else None
        return a.With(
            expressions=exprs,
            distinct=distinct or None,
            order=order,
            skip=skip,
            limit=limit,
            where=where,
            group_by=group_by,
        )

    def parse_return(self) -> a.Return:
        self._expect(TokenKind.RETURN)
        distinct = self._match(TokenKind.DISTINCT)
        exprs = self.parse_return_items()
        group_by = self._parse_group_by()
        order = self.parse_order_by() if self._check(TokenKind.ORDER) else None
        skip = a.Skip(this=self.parse_expression()) if self._match(TokenKind.SKIP) else None
        limit = a.Limit(this=self.parse_expression()) if self._match(TokenKind.LIMIT) else None
        return a.Return(
            expressions=exprs,
            distinct=distinct or None,
            order=order,
            skip=skip,
            limit=limit,
            group_by=group_by,
        )

    def parse_return_items(self) -> list[a.AstNode]:
        if self._match(TokenKind.STAR):
            return [a.Star()]
        items: list[a.AstNode] = []
        while True:
            expr = self.parse_expression()
            if self._match(TokenKind.AS):
                alias = self.parse_variable()
                items.append(a.Alias(this=expr, alias=alias))
            else:
                items.append(expr)
            if not self._match(TokenKind.COMMA):
                break
        return items

    def parse_order_by(self) -> a.Order:
        self._expect(TokenKind.ORDER)
        self._expect(TokenKind.BY)
        items: list[a.AstNode] = []
        while True:
            expr = self.parse_expression()
            desc = False
            if self._match(TokenKind.DESC):
                desc = True
            else:
                self._match(TokenKind.ASC)
            nulls = None
            # Contextual: ORDER BY … NULLS FIRST|LAST (idents, not reserved keywords)
            if self._check(TokenKind.IDENT) and self._peek().text.upper() == "NULLS":
                self._advance()
                if self._check(TokenKind.IDENT) and self._peek().text.upper() == "FIRST":
                    self._advance()
                    nulls = "FIRST"
                elif self._check(TokenKind.IDENT) and self._peek().text.upper() == "LAST":
                    self._advance()
                    nulls = "LAST"
                else:
                    raise self._err("Expected FIRST or LAST after NULLS", code="CG1102")
            items.append(a.Ordered(this=expr, desc=desc or None, nulls=nulls))
            if not self._match(TokenKind.COMMA):
                break
        return a.Order(expressions=items)

    def parse_create(self) -> a.Create:
        self._expect(TokenKind.CREATE)
        return a.Create(pattern=self.parse_pattern())

    def parse_insert(self) -> a.Insert:
        self._expect(TokenKind.INSERT)
        return a.Insert(pattern=self.parse_pattern())

    def parse_merge(self) -> a.Merge:
        self._expect(TokenKind.MERGE)
        pattern = self.parse_pattern()
        actions: list[a.AstNode] = []
        while self._check(TokenKind.ON):
            self._advance()
            if self._match(TokenKind.CREATE):
                self._expect(TokenKind.SET)
                actions.append(a.OnCreate(actions=[self.parse_set_body()]))
            elif self._match(TokenKind.MATCH):
                self._expect(TokenKind.SET)
                actions.append(a.OnMatch(actions=[self.parse_set_body()]))
            else:
                raise self._err("Expected CREATE or MATCH after ON", code="CG1102")
        return a.Merge(pattern=pattern, actions=actions or None)

    def parse_set(self) -> a.Set:
        self._expect(TokenKind.SET)
        return self.parse_set_body()

    def parse_set_body(self) -> a.Set:
        items: list[a.AstNode] = []
        while True:
            left = self.parse_set_target()
            if isinstance(left, a.NodePattern) and left.labels is not None:
                items.append(a.SetItem(this=left))
            else:
                op = "="
                if self._match(TokenKind.PLUS):
                    self._expect(TokenKind.EQ)
                    op = "+="
                else:
                    self._expect(TokenKind.EQ)
                right = self.parse_expression()
                items.append(
                    a.SetItem(this=left, expression=right, op=op if op != "=" else None)
                )
            if not self._match(TokenKind.COMMA):
                break
        return a.Set(items=items)

    def parse_set_target(self) -> a.AstNode:
        """SET LHS: property / variable / labels — must not consume ``=`` as comparison."""
        if self._match(TokenKind.LPAREN):
            node = self.parse_expression()
            self._expect(TokenKind.RPAREN)
            while self._match(TokenKind.DOT):
                node = a.Property(this=node, name=self._parse_unquoted_name())
        else:
            node = self.parse_postfix()
        if isinstance(node, a.LabelPredicate) and isinstance(node.this, a.Identifier):
            return a.NodePattern(variable=node.this, labels=node.labels)
        return node

    def parse_delete(self) -> a.Delete:
        detach = self._match(TokenKind.DETACH)
        self._expect(TokenKind.DELETE)
        exprs = self.parse_expression_list()
        return a.Delete(expressions=exprs, detach=detach or None)

    def parse_remove(self) -> a.Remove:
        self._expect(TokenKind.REMOVE)
        items: list[a.AstNode] = []
        while True:
            target = self.parse_postfix()
            if isinstance(target, a.LabelPredicate) and isinstance(target.this, a.Identifier):
                items.append(a.RemoveLabels(this=target.this, labels=target.labels))
            else:
                items.append(target)
            if not self._match(TokenKind.COMMA):
                break
        return a.Remove(items=items)

    def parse_foreach(self) -> a.Foreach:
        self._expect(TokenKind.FOREACH)
        self._expect(TokenKind.LPAREN)
        var = self.parse_variable()
        self._expect(TokenKind.IN)
        expr = self.parse_expression()
        self._expect(TokenKind.PIPE)
        clauses: list[a.AstNode] = []
        while not self._check(TokenKind.RPAREN):
            if self._check(TokenKind.CREATE):
                clauses.append(self.parse_create())
            elif self._check(TokenKind.MERGE):
                clauses.append(self.parse_merge())
            elif self._check(TokenKind.SET):
                clauses.append(self.parse_set())
            elif self._check(TokenKind.DELETE) or self._check(TokenKind.DETACH):
                clauses.append(self.parse_delete())
            elif self._check(TokenKind.REMOVE):
                clauses.append(self.parse_remove())
            elif self._check(TokenKind.FOREACH):
                clauses.append(self.parse_foreach())
            else:
                raise self._err("Invalid FOREACH body clause", code="CG1102")
        self._expect(TokenKind.RPAREN)
        return a.Foreach(variable=var, expression=expr, clauses=clauses)

    def parse_call(self) -> a.CallSubquery | a.CallProcedure:
        """Parse ``CALL { … }`` subquery or ``CALL ns.proc(…) [YIELD …]``."""
        optional = self._match(TokenKind.OPTIONAL)
        if optional and not self._dialect_allows("allow_optional_call"):
            raise self._err("OPTIONAL CALL requires neo4j25", code="CG1102")
        self._expect(TokenKind.CALL)
        if self._check(TokenKind.LPAREN) or self._check(TokenKind.LBRACE):
            return self._parse_call_subquery_body(optional=optional or None)
        if optional:
            raise self._err("OPTIONAL CALL requires a subquery", code="CG1102")
        return self._parse_call_procedure_body()

    def parse_call_subquery(self) -> a.CallSubquery:
        """Parse ``CALL { query }`` (Neo4j subquery form; parse-tolerant)."""
        self._expect(TokenKind.CALL)
        return self._parse_call_subquery_body()

    def _parse_call_subquery_body(self, *, optional: bool | None = None) -> a.CallSubquery:
        variables: list[a.AstNode] | a.Star | None = None
        if self._match(TokenKind.LPAREN):
            if not self._dialect_allows("allow_call_variable_import"):
                raise self._err(
                    "CALL (vars) import requires neo4j5+ dialect",
                    code="CG1102",
                )
            if self._match(TokenKind.STAR):
                variables = a.Star()
            else:
                variables = []
                while True:
                    variables.append(self.parse_variable())
                    if not self._match(TokenKind.COMMA):
                        break
            self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.LBRACE)
        inner = self.parse_statement()
        self._expect(TokenKind.RBRACE)
        in_transactions = False
        transaction_rows: a.AstNode | None = None
        if self._check(TokenKind.IN) and self._check_word("TRANSACTIONS", 1):
            if not self._dialect_allows("allow_call_in_transactions"):
                raise self._err("IN TRANSACTIONS requires neo4j25", code="CG1102")
            self._advance()
            self._expect_word("TRANSACTIONS")
            in_transactions = True
            if self._match_word("OF"):
                transaction_rows = self.parse_expression()
                self._match_word("ROWS")
        return a.CallSubquery(
            query=inner,
            variables=variables,
            optional=optional,
            in_transactions=in_transactions or None,
            transaction_rows=transaction_rows,
        )

    def _parse_call_procedure_body(self) -> a.CallProcedure:
        """``ns.proc(args) [YIELD items|*] [WHERE expr]`` (CALL already consumed)."""
        name = self._parse_procedure_name()
        args: list[a.AstNode] = []
        if self._match(TokenKind.LPAREN):
            if not self._check(TokenKind.RPAREN):
                args = self.parse_expression_list()
            self._expect(TokenKind.RPAREN)
        yield_: a.Yield | None = None
        where: a.Where | None = None
        if self._match(TokenKind.YIELD):
            yield_ = a.Yield(expressions=self._parse_yield_items())
            if self._match(TokenKind.WHERE):
                where = a.Where(this=self.parse_expression())
        return a.CallProcedure(name=name, expressions=args, yield_=yield_, where=where)

    def _parse_procedure_name(self) -> str:
        parts: list[str] = [self._expect(TokenKind.IDENT).text]
        while self._match(TokenKind.DOT):
            parts.append(self._expect(TokenKind.IDENT).text)
        return ".".join(parts)

    def _parse_yield_items(self) -> list[a.AstNode]:
        if self._match(TokenKind.STAR):
            return [a.Star()]
        items: list[a.AstNode] = []
        while True:
            ident = self.parse_variable()
            if self._match(TokenKind.AS):
                alias = self.parse_variable()
                items.append(a.Alias(this=ident, alias=alias))
            else:
                items.append(ident)
            if not self._match(TokenKind.COMMA):
                break
        return items

    # --- patterns ---------------------------------------------------------

    def parse_pattern(self) -> a.Pattern:
        paths = [self.parse_path_pattern()]
        while self._match(TokenKind.COMMA):
            paths.append(self.parse_path_pattern())
        return a.Pattern(paths=paths)

    def parse_path_pattern(self) -> a.PathPattern:
        with self._nesting():
            return self._parse_path_pattern_body()

    def _parse_path_pattern_body(self) -> a.PathPattern:
        variable = None
        # named path: p = (n)-[]->(m)
        if self._check(TokenKind.IDENT) and self._check_ahead(TokenKind.EQ):
            variable = self.parse_variable()
            self._expect(TokenKind.EQ)

        # shortestPath / allShortestPaths
        if self._check(TokenKind.SHORTESTPATH) or self._check(TokenKind.ALLSHORTESTPATHS):
            all_ = self._match(TokenKind.ALLSHORTESTPATHS)
            if not all_:
                self._expect(TokenKind.SHORTESTPATH)
            self._expect(TokenKind.LPAREN)
            path = self.parse_path_pattern()
            self._expect(TokenKind.RPAREN)
            node = a.ShortestPath(this=path, all_=all_ or None)
            return a.PathPattern(variable=variable, elements=[node])

        # Neo4j QPP: ((n)-[:R]->(m)){1,3}  or  ((n)-[:R]->(m))+
        if self._check(TokenKind.LPAREN) and self._peek(1).kind is TokenKind.LPAREN:
            saved = self._i
            self._advance()  # outer (
            try:
                inner = self.parse_path_pattern()
                self._expect(TokenKind.RPAREN)
                if (
                    self._check(TokenKind.LBRACE)
                    or self._check(TokenKind.STAR)
                    or self._check(TokenKind.PLUS)
                ):
                    min_hops, max_hops = self._parse_path_quantifier()
                    q = a.QuantifiedPath(this=inner, min_hops=min_hops, max_hops=max_hops)
                    return a.PathPattern(variable=variable, elements=[q])
            except ParseError:
                pass
            self._i = saved

        elements: list[a.AstNode] = [self.parse_node_pattern()]
        while self._is_rel_start():
            elements.append(self.parse_relationship_pattern())
            elements.append(self.parse_node_pattern())
        return a.PathPattern(variable=variable, elements=elements)

    def _parse_path_quantifier(self) -> tuple[int | None, int | None]:
        """Parse ``{lo,hi}``, ``*``, or ``+`` after a grouped path. Defaults to {1,1}."""
        if self._match(TokenKind.LBRACE):
            min_hops: int | None = None
            max_hops: int | None = None
            if self._check(TokenKind.INTEGER):
                min_hops = int(self._advance().text)
            if self._match(TokenKind.COMMA):
                if self._check(TokenKind.INTEGER):
                    max_hops = int(self._advance().text)
            else:
                max_hops = min_hops
            self._expect(TokenKind.RBRACE)
            return min_hops, max_hops
        if self._match(TokenKind.STAR):
            return 0, None
        if self._match(TokenKind.PLUS):
            return 1, None
        return 1, 1

    def _is_rel_start(self) -> bool:
        return (
            self._check(TokenKind.MINUS)
            or self._check(TokenKind.ARROW_LEFT)
            or self._check(TokenKind.ARROW_RIGHT)
        )

    def parse_node_pattern(self) -> a.NodePattern:
        self._expect(TokenKind.LPAREN)
        variable = None
        labels = None
        properties = None
        if self._check(TokenKind.IDENT):
            variable = self.parse_variable()
        if self._check(TokenKind.COLON):
            labels = self._parse_labels()
        if self._check(TokenKind.LBRACE):
            properties = self.parse_map_literal()
        where = None
        if self._match(TokenKind.WHERE):
            if not self._dialect_allows("allow_inline_pattern_where"):
                raise self._err(
                    "Inline pattern WHERE requires neo4j5+ dialect",
                    code="CG1102",
                )
            where = a.Where(this=self.parse_expression())
        self._expect(TokenKind.RPAREN)
        return a.NodePattern(variable=variable, labels=labels, properties=properties, where=where)

    def _parse_labels(self) -> a.LabelExpression:
        """Parse ``:A:B`` (AND), ``:A|B`` (OR), or ``:!A&B`` label expressions."""
        if not self._match(TokenKind.COLON):
            return a.LabelExpression(labels=[])
        if self._dialect_allows("allow_dynamic_labels") and self._check(TokenKind.PARAMETER):
            param = self.parse_primary()
            if isinstance(param, a.Parameter):
                return a.LabelExpression(labels=[], expression=f"${param.name}")
        if self._dialect_allows("allow_label_expressions") and (
            self._check(TokenKind.BANG) or self._check(TokenKind.LPAREN)
        ):
            return a.LabelExpression(labels=[], expression=self._parse_label_expr_text())
        first = self._parse_unquoted_name()
        if self._dialect_allows("allow_label_expressions") and self._check_any(
            TokenKind.AMP, TokenKind.PIPE, TokenKind.PERCENT
        ):
            body = first
            while True:
                if self._match(TokenKind.AMP):
                    body += "&" + self._parse_unquoted_name()
                elif self._match(TokenKind.PIPE):
                    body += "|" + self._parse_unquoted_name()
                elif self._match(TokenKind.PERCENT):
                    body += "%"
                else:
                    break
            return a.LabelExpression(labels=[], expression=body)
        if self._match(TokenKind.PIPE):
            parts = [first]
            while True:
                parts.append(self._parse_unquoted_name())
                if not self._match(TokenKind.PIPE):
                    break
            return a.LabelExpression(labels=[], expression="|".join(parts))
        labels = [first]
        while self._match(TokenKind.COLON):
            labels.append(self._parse_unquoted_name())
        return a.LabelExpression(labels=labels)

    def _parse_label_expr_text(self) -> str:
        parts: list[str] = []
        while True:
            if self._match(TokenKind.BANG):
                parts.append("!")
            elif self._match(TokenKind.LPAREN):
                inner = self._parse_label_expr_text()
                parts.append(f"({inner})")
                self._expect(TokenKind.RPAREN)
            else:
                parts.append(self._parse_unquoted_name())
            if self._match(TokenKind.AMP):
                parts.append("&")
                continue
            if self._match(TokenKind.PIPE):
                parts.append("|")
                continue
            break
        return "".join(parts)

    def _parse_unquoted_name(self) -> str:
        """Label, rel type, property, or map key — keywords allowed (e.g. ``End``, ``count``)."""
        tok = self._peek()
        if tok.kind in {
            TokenKind.RBRACKET,
            TokenKind.LBRACE,
            TokenKind.STAR,
            TokenKind.COMMA,
            TokenKind.PIPE,
            TokenKind.COLON,
            TokenKind.RPAREN,
            TokenKind.EOF,
        }:
            raise self._err("Expected name", code="CG1104")
        self._advance()
        return self._name_from_token(tok)

    def _name_from_token(self, tok: Token) -> str:
        if tok.kind is TokenKind.IDENT:
            return tok.text
        off = tok.position.offset
        i = off
        while i < len(self.source) and (self.source[i].isalnum() or self.source[i] == "_"):
            i += 1
        return self.source[off:i]

    def parse_relationship_pattern(self) -> a.RelationshipPattern:
        direction = a.Direction.BOTH
        if self._match(TokenKind.ARROW_LEFT):
            direction = a.Direction.INCOMING
            # <-[...]-  or  <--  or  <-->
            if self._check(TokenKind.LBRACKET):
                rel = self._parse_rel_detail(direction)
                if self._match(TokenKind.ARROW_RIGHT):
                    rel.direction = a.Direction.BOTH
                else:
                    self._expect(TokenKind.MINUS)
                return rel
            if self._match(TokenKind.ARROW_RIGHT):
                return a.RelationshipPattern(direction=a.Direction.BOTH)
            self._expect(TokenKind.MINUS)
            return a.RelationshipPattern(direction=direction)
        # starts with -
        self._expect(TokenKind.MINUS)
        if self._check(TokenKind.LBRACKET):
            rel = self._parse_rel_detail(a.Direction.BOTH)
            if self._match(TokenKind.ARROW_RIGHT):
                rel.direction = a.Direction.OUTGOING
            else:
                self._expect(TokenKind.MINUS)
            return rel
        if self._match(TokenKind.ARROW_RIGHT):
            return a.RelationshipPattern(direction=a.Direction.OUTGOING)
        # anonymous undirected ``--`` (second ``-``)
        self._match(TokenKind.MINUS)
        return a.RelationshipPattern(direction=a.Direction.BOTH)

    def _parse_rel_detail(self, direction: a.Direction) -> a.RelationshipPattern:
        self._expect(TokenKind.LBRACKET)
        variable = None
        types: list[str] | None = None
        properties = None
        variable_length = False
        min_hops: int | None = None
        max_hops: int | None = None

        if self._check(TokenKind.IDENT):
            variable = self.parse_variable()
        if self._match(TokenKind.COLON):
            types = [self._parse_type_name()]
            while self._match(TokenKind.PIPE):
                # optional colon before next type
                self._match(TokenKind.COLON)
                types.append(self._parse_type_name())
        memgraph_quantifier: str | None = None
        memgraph_weight_expr: a.AstNode | None = None
        memgraph_total_weight: a.AstNode | None = None
        if self._match(TokenKind.STAR):
            variable_length = True
            if self._dialect_allows("allow_memgraph_rel_quantifiers"):
                memgraph_quantifier = self._parse_memgraph_quantifier_name()
            if self._check(TokenKind.INTEGER):
                min_hops = int(self._advance().text)
                if self._match(TokenKind.DOTDOT):
                    max_hops = int(self._advance().text) if self._check(TokenKind.INTEGER) else None
                else:
                    max_hops = min_hops
            elif self._match(TokenKind.DOTDOT):
                min_hops = 1
                if self._check(TokenKind.INTEGER):
                    max_hops = int(self._advance().text)
            elif memgraph_quantifier is None:
                min_hops = 1
                max_hops = None
            if memgraph_quantifier is not None:
                # Memgraph puts the lambda and total-weight binding after the bounds:
                # ``*wShortest 5 (e, n | e.weight) total``.
                if self._check(TokenKind.LPAREN):
                    memgraph_weight_expr = self._parse_relationship_lambda()
                if memgraph_quantifier == "wShortest" and self._check(TokenKind.IDENT):
                    memgraph_total_weight = self.parse_variable()
        if self._check(TokenKind.LBRACE):
            properties = self.parse_map_literal()
        where = None
        if self._match(TokenKind.WHERE):
            if not self._dialect_allows("allow_inline_pattern_where"):
                raise self._err(
                    "Inline pattern WHERE requires neo4j5+ dialect",
                    code="CG1102",
                )
            where = a.Where(this=self.parse_expression())
        self._expect(TokenKind.RBRACKET)
        return a.RelationshipPattern(
            variable=variable,
            types=types,
            properties=properties,
            direction=direction,
            min_hops=min_hops,
            max_hops=max_hops,
            variable_length=variable_length or None,
            where=where,
            memgraph_quantifier=memgraph_quantifier,
            memgraph_weight_expr=memgraph_weight_expr,
            memgraph_total_weight=memgraph_total_weight,
        )

    def _parse_memgraph_quantifier_name(self) -> str | None:
        if not self._check(TokenKind.IDENT):
            return None
        qname = self._peek().text.lower()
        if qname == "bfs":
            self._advance()
            return "bfs"
        if qname in ("wshortest", "wshortestpath"):
            self._advance()
            return "wShortest"
        return None

    def _parse_relationship_lambda(self) -> a.RelationshipLambda:
        """``(rel, node | expr)`` weight or filter lambda on a Memgraph quantifier."""
        self._expect(TokenKind.LPAREN)
        relationship = self.parse_variable()
        self._expect(TokenKind.COMMA)
        node = self.parse_variable()
        self._expect(TokenKind.PIPE)
        expression = self.parse_expression()
        self._expect(TokenKind.RPAREN)
        return a.RelationshipLambda(
            relationship=relationship,
            node=node,
            expression=expression,
        )

    def _parse_type_name(self) -> str:
        """Relationship or label name — may be a keyword (e.g. ``CONTAINS``, ``End``)."""
        tok = self._peek()
        if tok.kind in {
            TokenKind.RBRACKET,
            TokenKind.LBRACE,
            TokenKind.STAR,
            TokenKind.COMMA,
            TokenKind.PIPE,
            TokenKind.COLON,
            TokenKind.RPAREN,
            TokenKind.EOF,
        }:
            raise self._err("Expected type name", code="CG1104")
        self._advance()
        return self._name_from_token(tok)

    def _parse_quantifier(self, name: str) -> a.Quantifier:
        self._expect(TokenKind.LPAREN)
        var = self.parse_variable()
        self._expect(TokenKind.IN)
        source = self.parse_expression()
        where_expr: a.AstNode | None = None
        if self._match(TokenKind.WHERE):
            where_expr = self.parse_expression()
        self._expect(TokenKind.RPAREN)
        return a.Quantifier(name=name.lower(), variable=var, source=source, where=where_expr)

    def _parse_list_lambda(self, name: str) -> a.ListLambda:
        """Parse legacy filter/extract and reduce expression syntax."""
        lower = name.lower()
        self._expect(TokenKind.LPAREN)
        accumulator: a.Identifier | None = None
        initial: a.AstNode | None = None
        if lower == "reduce":
            accumulator = self.parse_variable()
            self._expect(TokenKind.EQ)
            initial = self.parse_expression()
            self._expect(TokenKind.COMMA)
        variable = self.parse_variable()
        self._expect(TokenKind.IN)
        source = self.parse_expression()
        if lower == "filter":
            self._expect(TokenKind.WHERE)
        else:
            self._expect(TokenKind.PIPE)
        expression = self.parse_expression()
        self._expect(TokenKind.RPAREN)
        return a.ListLambda(
            name=lower,
            variable=variable,
            source=source,
            expression=expression,
            accumulator=accumulator,
            initial=initial,
        )

    def _parse_count_subquery(self) -> a.CountSubquery:
        self._expect(TokenKind.COUNT)
        self._expect(TokenKind.LBRACE)
        if self._looks_like_pattern_start():
            query: a.AstNode = self.parse_path_pattern()
        else:
            query = self.parse_statement()
        self._expect(TokenKind.RBRACE)
        return a.CountSubquery(query=query)

    # --- expressions (Pratt-ish precedence climbing) ----------------------

    def parse_expression(self) -> a.AstNode:
        with self._nesting():
            return self.parse_or()

    def parse_expression_list(self) -> list[a.AstNode]:
        items = [self.parse_expression()]
        while self._match(TokenKind.COMMA):
            items.append(self.parse_expression())
        return items

    def parse_or(self) -> a.AstNode:
        left = self.parse_xor()
        while self._match(TokenKind.OR):
            left = a.Or(this=left, expression=self.parse_xor())
        return left

    def parse_xor(self) -> a.AstNode:
        left = self.parse_and()
        while self._match(TokenKind.XOR):
            left = a.Xor(this=left, expression=self.parse_and())
        return left

    def parse_and(self) -> a.AstNode:
        left = self.parse_not()
        while self._match(TokenKind.AND):
            left = a.And(this=left, expression=self.parse_not())
        return left

    def parse_not(self) -> a.AstNode:
        if self._match(TokenKind.NOT):
            # Pattern predicate: NOT (n)-[:R]->() / NOT ((n)-[:R]->())
            if self._check(TokenKind.LPAREN) and self._looks_like_pattern_start():
                # Optional extra wrapping paren: NOT ((path))
                extra = False
                if self._peek(1).kind is TokenKind.LPAREN and self._inner_looks_like_pattern(1):
                    self._advance()  # consume outer (
                    extra = True
                pred = a.PatternPredicate(pattern=self.parse_path_pattern(), not_=True)
                if extra:
                    self._expect(TokenKind.RPAREN)
                return pred
            return a.Not(this=self.parse_not())
        # EXISTS { … } / EXISTS (pattern) handled in primary
        return self.parse_comparison()

    def _inner_looks_like_pattern(self, from_paren_offset: int) -> bool:
        """True if token after a ``(`` at ``from_paren_offset`` starts a node pattern."""
        # from_paren_offset=0 → current is (; =1 → peek(1) is (
        base = from_paren_offset
        if self._peek(base).kind is not TokenKind.LPAREN:
            return False
        n1 = self._peek(base + 1).kind
        n2 = self._peek(base + 2).kind
        if n1 in (TokenKind.COLON, TokenKind.RPAREN, TokenKind.LBRACE, TokenKind.LPAREN):
            return True
        return n1 is TokenKind.IDENT and n2 in (
            TokenKind.COLON,
            TokenKind.RPAREN,
            TokenKind.LBRACE,
            TokenKind.MINUS,
            TokenKind.ARROW_LEFT,
            TokenKind.ARROW_RIGHT,
        )

    def _looks_like_pattern_start(self) -> bool:
        """True if ``(`` begins a node pattern rather than a parenthesized expression."""
        if not self._check(TokenKind.LPAREN):
            return False
        # NOT ((path)) — outer paren wraps a pattern
        if self._peek(1).kind is TokenKind.LPAREN and self._inner_looks_like_pattern(1):
            return True
        return self._inner_looks_like_pattern(0)

    def parse_comparison(self) -> a.AstNode:
        left = self.parse_add()
        while True:
            if self._match(TokenKind.EQ):
                left = a.EQ(this=left, expression=self.parse_add())
            elif self._match(TokenKind.NEQ):
                left = a.NEQ(this=left, expression=self.parse_add())
            elif self._match(TokenKind.LT):
                left = a.LT(this=left, expression=self.parse_add())
            elif self._match(TokenKind.GT):
                left = a.GT(this=left, expression=self.parse_add())
            elif self._match(TokenKind.LTE):
                left = a.LTE(this=left, expression=self.parse_add())
            elif self._match(TokenKind.GTE):
                left = a.GTE(this=left, expression=self.parse_add())
            elif self._match(TokenKind.REGEX):
                left = a.RegexMatch(this=left, expression=self.parse_add())
            elif self._check(TokenKind.STARTS):
                self._advance()
                self._expect(TokenKind.WITH)
                left = a.StartsWith(this=left, expression=self.parse_add())
            elif self._check(TokenKind.ENDS):
                self._advance()
                self._expect(TokenKind.WITH)
                left = a.EndsWith(this=left, expression=self.parse_add())
            elif self._match(TokenKind.CONTAINS):
                left = a.Contains(this=left, expression=self.parse_add())
            elif self._match(TokenKind.IN):
                left = a.In(this=left, expression=self.parse_add())
            elif self._match(TokenKind.IS):
                not_ = self._match(TokenKind.NOT)
                self._expect(TokenKind.NULL_KW)
                left = a.IsNull(this=left, not_=not_ or None)
            else:
                break
        return left

    def parse_add(self) -> a.AstNode:
        left = self.parse_mul()
        while True:
            if self._match(TokenKind.PLUS):
                left = a.Add(this=left, expression=self.parse_mul())
            elif self._match(TokenKind.MINUS):
                left = a.Sub(this=left, expression=self.parse_mul())
            else:
                break
        return left

    def parse_mul(self) -> a.AstNode:
        left = self.parse_pow()
        while True:
            if self._match(TokenKind.STAR):
                left = a.Mul(this=left, expression=self.parse_pow())
            elif self._match(TokenKind.SLASH):
                left = a.Div(this=left, expression=self.parse_pow())
            elif self._match(TokenKind.PERCENT):
                left = a.Mod(this=left, expression=self.parse_pow())
            else:
                break
        return left

    def parse_pow(self) -> a.AstNode:
        left = self.parse_unary()
        if self._match(TokenKind.CARET):
            return a.Pow(this=left, expression=self.parse_pow())
        return left

    def parse_unary(self) -> a.AstNode:
        if self._match(TokenKind.PLUS):
            return self.parse_unary()
        if self._match(TokenKind.MINUS):
            return a.Neg(this=self.parse_unary())
        return self.parse_postfix()

    def parse_postfix(self) -> a.AstNode:
        node = self.parse_primary()
        while True:
            if self._match(TokenKind.DOT):
                name = self._parse_unquoted_name()
                node = a.Property(this=node, name=name)
                if self._check(TokenKind.LBRACE):
                    entries = self._parse_map_projection_entries()
                    node = a.MapProjection(this=node, entries=entries)
            elif self._check(TokenKind.LBRACE) and isinstance(node, a.Identifier):
                entries = self._parse_map_projection_entries()
                node = a.MapProjection(this=node, entries=entries)
            elif self._match(TokenKind.LBRACKET):
                if self._match(TokenKind.DOTDOT):
                    end = None if self._check(TokenKind.RBRACKET) else self.parse_expression()
                    self._expect(TokenKind.RBRACKET)
                    node = a.ListSlice(this=node, start=None, end=end)
                else:
                    first = self.parse_expression()
                    if self._match(TokenKind.DOTDOT):
                        end = None if self._check(TokenKind.RBRACKET) else self.parse_expression()
                        self._expect(TokenKind.RBRACKET)
                        node = a.ListSlice(this=node, start=first, end=end)
                    else:
                        self._expect(TokenKind.RBRACKET)
                        node = a.ListSubscript(this=node, index=first)
            elif self._check(TokenKind.COLON) and isinstance(node, a.Identifier):
                labels = self._parse_labels()
                node = a.LabelPredicate(this=node, labels=labels)
            else:
                break
        return node

    def parse_primary(self) -> a.AstNode:
        tok = self._peek()
        if tok.kind is TokenKind.INTEGER:
            self._advance()
            lower = tok.text.lower()
            base = 16 if lower.startswith("0x") else 8 if lower.startswith("0o") else 10
            return a.Integer(this=int(tok.text, base))
        if tok.kind is TokenKind.FLOAT:
            self._advance()
            return a.Float(this=float(tok.text))
        if tok.kind is TokenKind.STRING:
            self._advance()
            return a.String(this=tok.text)
        if tok.kind is TokenKind.TRUE:
            self._advance()
            return a.Boolean(this=True)
        if tok.kind is TokenKind.FALSE:
            self._advance()
            return a.Boolean(this=False)
        if tok.kind is TokenKind.NULL_KW:
            self._advance()
            return a.Null()
        if tok.kind is TokenKind.PARAMETER:
            self._advance()
            return a.Parameter(name=tok.text)
        if tok.kind is TokenKind.CASE:
            return self.parse_case()
        if tok.kind is TokenKind.LBRACKET:
            return self.parse_list_or_comprehension()
        if tok.kind is TokenKind.LBRACE:
            return self.parse_map_literal()
        if tok.kind is TokenKind.EXISTS:
            return self.parse_exists()
        if tok.kind is TokenKind.COUNT and self._peek(1).kind is TokenKind.LBRACE:
            return self._parse_count_subquery()
        if tok.kind in (TokenKind.ALL, TokenKind.ANY, TokenKind.NONE, TokenKind.SINGLE):
            return self._parse_quantifier(self._advance().text)
        if tok.kind is TokenKind.LPAREN:
            # Could be parenthesized expr OR a pattern (node) in expression context
            return self._parse_paren_or_pattern()
        # Function call or identifier
        if tok.kind is TokenKind.IDENT or tok.kind in (
            TokenKind.COUNT,
            TokenKind.COLLECT,
            TokenKind.SHORTESTPATH,
            TokenKind.ALLSHORTESTPATHS,
            TokenKind.FILTER,
        ):
            name_tok = self._advance()
            name = name_tok.text
            if name_tok.kind is not TokenKind.IDENT:
                name = name_tok.kind.name  # COUNT etc.
                if name_tok.kind is TokenKind.SHORTESTPATH:
                    name = "shortestPath"
                elif name_tok.kind is TokenKind.ALLSHORTESTPATHS:
                    name = "allShortestPaths"
                else:
                    name = name.lower()
            if name.lower() in {"extract", "filter", "reduce"}:
                return self._parse_list_lambda(name)
            if self._check(TokenKind.DOT):
                probe = self._i
                dotted = name
                while self._match(TokenKind.DOT):
                    dotted += "." + self._parse_unquoted_name()
                if self._match(TokenKind.LPAREN):
                    distinct = self._match(TokenKind.DISTINCT)
                    if self._match(TokenKind.STAR) and dotted.lower() == "count":
                        self._expect(TokenKind.RPAREN)
                        return a.FunctionCall(name="count", expressions=[a.Star()], distinct=None)
                    args: list[a.AstNode] = []
                    if not self._check(TokenKind.RPAREN):
                        args = self.parse_expression_list()
                    self._expect(TokenKind.RPAREN)
                    if dotted.lower() == "coalesce":
                        return a.Coalesce(expressions=args)
                    return a.FunctionCall(name=dotted, expressions=args, distinct=distinct or None)
                self._i = probe
            if self._match(TokenKind.LPAREN):
                distinct = self._match(TokenKind.DISTINCT)
                if self._match(TokenKind.STAR) and name.lower() == "count":
                    self._expect(TokenKind.RPAREN)
                    return a.FunctionCall(name="count", expressions=[a.Star()], distinct=None)
                fn_args: list[a.AstNode] = []
                if not self._check(TokenKind.RPAREN):
                    fn_args = self.parse_expression_list()
                self._expect(TokenKind.RPAREN)
                if name.lower() == "coalesce":
                    return a.Coalesce(expressions=fn_args)
                return a.FunctionCall(name=name, expressions=fn_args, distinct=distinct or None)
            return a.Identifier(this=name)
        raise self._err(f"Unexpected token {tok.text!r}", code="CG1101")

    def parse_exists(self) -> a.AstNode:
        """``EXISTS { query }`` or ``EXISTS ( pattern )`` / ``exists(expr)``."""
        self._expect(TokenKind.EXISTS)
        if self._match(TokenKind.LBRACE):
            if self._looks_like_pattern_start():
                path = self.parse_path_pattern()
                where = (
                    a.Where(this=self.parse_expression())
                    if self._match(TokenKind.WHERE)
                    else None
                )
                inner: a.AstNode = a.Query(
                    clauses=[a.Match(pattern=a.Pattern(paths=[path]), where=where)]
                )
            else:
                inner = self.parse_statement()
            self._expect(TokenKind.RBRACE)
            return a.PatternPredicate(pattern=inner, not_=False)
        self._expect(TokenKind.LPAREN)
        # EXISTS ((n)-->(m)) — outer paren already consumed; path starts at next '('
        if self._check(TokenKind.LPAREN) or self._looks_like_pattern_start():
            # If current is LPAREN, path parser consumes it; if we already ate outer and
            # look-ahead says pattern, rewind one so path sees the node '('.
            if not self._check(TokenKind.LPAREN):
                self._i -= 1
            path = self.parse_path_pattern()
            self._expect(TokenKind.RPAREN)
            return a.PatternPredicate(pattern=path, not_=False)
        expr = self.parse_expression()
        self._expect(TokenKind.RPAREN)
        return a.FunctionCall(name="exists", expressions=[expr])

    def _parse_paren_or_pattern(self) -> a.AstNode:
        """Parenthesized expression, or positive pattern predicate ``(a)-[:R]->(b)``."""
        # Pattern predicate: WHERE (n)-[:R]->(:L) or WHERE ((n)-[:R]->(:L))
        if self._looks_like_pattern_start():
            saved = self._i
            try:
                extra = False
                if self._peek(1).kind is TokenKind.LPAREN and self._inner_looks_like_pattern(1):
                    self._advance()  # outer (
                    extra = True
                path = self.parse_path_pattern()
                # Relationship path → pattern predicate (same as NOT (path))
                if len(path.elements) > 1:
                    if extra:
                        self._expect(TokenKind.RPAREN)
                    else:
                        self._match(TokenKind.RPAREN)  # optional trailing )
                    return a.PatternPredicate(pattern=path, not_=False)
                # Single-node path: only treat labelled / props as predicate; bare (n) → below
                if (
                    len(path.elements) == 1
                    and isinstance(path.elements[0], a.NodePattern)
                    and (
                        path.elements[0].labels is not None
                        or path.elements[0].properties is not None
                    )
                ):
                    if extra:
                        self._expect(TokenKind.RPAREN)
                    else:
                        self._match(TokenKind.RPAREN)
                    return a.PatternPredicate(pattern=path, not_=False)
                self._i = saved
            except ParseError:
                self._i = saved

        self._expect(TokenKind.LPAREN)
        # Heuristic: if we see a node pattern shape, try pattern / (n) unwrap
        if (
            self._check(TokenKind.IDENT)
            or self._check(TokenKind.COLON)
            or self._check(TokenKind.RPAREN)
            or self._check(TokenKind.LBRACE)
        ):
            saved = self._i
            try:
                self._i = saved - 1
                path = self.parse_path_pattern()
                if self._match(TokenKind.WHERE):
                    self.parse_expression()
                if self._match(TokenKind.PIPE):
                    self.parse_expression()
                if (
                    len(path.elements) == 1
                    and isinstance(path.elements[0], a.NodePattern)
                    and path.elements[0].labels is None
                    and path.elements[0].properties is None
                    and path.elements[0].variable is not None
                    and self._check(TokenKind.RPAREN)
                ):
                    self._advance()
                    var = path.elements[0].variable
                    assert isinstance(var, a.AstNode)
                    return var
                if len(path.elements) > 1:
                    self._match(TokenKind.RPAREN)
                    return a.PatternPredicate(pattern=path, not_=False)
                if self._match(TokenKind.RPAREN):
                    return path
            except ParseError:
                self._i = saved
        # Standard parenthesized expression
        expr = self.parse_expression()
        self._expect(TokenKind.RPAREN)
        return expr

    def parse_list_or_comprehension(self) -> a.AstNode:
        self._expect(TokenKind.LBRACKET)
        if self._check(TokenKind.RBRACKET):
            self._advance()
            return a.List(expressions=[])
        # Pattern comprehension: [p = (n)-->(m) | m.x] or [(n)-->(m) | m.x]
        if self._check(TokenKind.IDENT):
            saved = self._i
            var = self.parse_variable()
            if self._match(TokenKind.EQ):
                try:
                    path = self.parse_path_pattern()
                    where: a.Where | None = (
                        a.Where(this=self.parse_expression())
                        if self._match(TokenKind.WHERE)
                        else None
                    )
                    if self._match(TokenKind.PIPE):
                        proj = self.parse_expression()
                        self._expect(TokenKind.RBRACKET)
                        return a.PatternComprehension(
                            variable=var, pattern=path, where=where, projection=proj
                        )
                except ParseError:
                    pass
                self._i = saved
            else:
                self._i = saved
        if self._check(TokenKind.LPAREN):
            saved = self._i
            try:
                path = self.parse_path_pattern()
                where = (
                    a.Where(this=self.parse_expression()) if self._match(TokenKind.WHERE) else None
                )
                if self._match(TokenKind.PIPE):
                    proj = self.parse_expression()
                    self._expect(TokenKind.RBRACKET)
                    return a.PatternComprehension(pattern=path, where=where, projection=proj)
                self._i = saved
            except ParseError:
                self._i = saved
        # List literal or list comprehension: [x IN list WHERE ... | x]
        # Must detect `IDENT IN` before parse_expression (else `x IN ys` becomes In node).
        if self._check(TokenKind.IDENT) and self._peek(1).kind is TokenKind.IN:
            var = self.parse_variable()
            self._expect(TokenKind.IN)
            source = self.parse_expression()
            where_expr: a.AstNode | None = None
            if self._match(TokenKind.WHERE):
                where_expr = self.parse_expression()
            projection = None
            if self._match(TokenKind.PIPE):
                projection = self.parse_expression()
            self._expect(TokenKind.RBRACKET)
            return a.ListComprehension(
                variable=var, source=source, where=where_expr, projection=projection
            )
        items: list[a.AstNode] = [self.parse_expression()]
        while self._match(TokenKind.COMMA):
            items.append(self.parse_expression())
        self._expect(TokenKind.RBRACKET)
        return a.List(expressions=items)

    def parse_map_literal(self) -> a.Map:
        self._expect(TokenKind.LBRACE)
        entries: list[tuple[str, a.AstNode]] = []
        if not self._check(TokenKind.RBRACE):
            while True:
                key = self._parse_unquoted_name()
                self._expect(TokenKind.COLON)
                val = self.parse_expression()
                entries.append((key, val))
                if not self._match(TokenKind.COMMA):
                    break
        self._expect(TokenKind.RBRACE)
        return a.Map(entries=entries)

    def _parse_map_projection_entries(self) -> list[t.Any]:
        self._expect(TokenKind.LBRACE)
        entries: list[t.Any] = []
        if not self._check(TokenKind.RBRACE):
            while True:
                if self._match(TokenKind.DOT):
                    if self._match(TokenKind.STAR):
                        entries.append(a.Star())
                    elif self._check(TokenKind.IDENT):
                        entries.append(a.PropertySelector(name=self._advance().text))
                    else:
                        raise self._err("Invalid map projection entry", code="CG1102")
                elif self._check(TokenKind.IDENT):
                    name = self._advance().text
                    if self._match(TokenKind.COLON):
                        entries.append((name, self.parse_expression()))
                    else:
                        entries.append(name)
                else:
                    raise self._err("Invalid map projection entry", code="CG1102")
                if not self._match(TokenKind.COMMA):
                    break
        self._expect(TokenKind.RBRACE)
        return entries

    def parse_case(self) -> a.Case:
        self._expect(TokenKind.CASE)
        this = None
        if not self._check(TokenKind.WHEN):
            this = self.parse_expression()
        ifs: list[tuple[a.AstNode, a.AstNode]] = []
        while self._match(TokenKind.WHEN):
            cond = self.parse_expression()
            self._expect(TokenKind.THEN)
            then = self.parse_expression()
            ifs.append((cond, then))
        default = None
        if self._match(TokenKind.ELSE):
            default = self.parse_expression()
        self._expect(TokenKind.END)
        return a.Case(this=this, ifs=ifs, default=default)

    def parse_variable(self) -> a.Identifier:
        tok = self._peek()
        if tok.kind is TokenKind.IDENT:
            self._advance()
            return a.Identifier(this=tok.text)
        if tok.kind not in {
            TokenKind.EOF,
            TokenKind.LPAREN,
            TokenKind.RPAREN,
            TokenKind.LBRACKET,
            TokenKind.RBRACE,
            TokenKind.LBRACE,
            TokenKind.COMMA,
            TokenKind.SEMICOLON,
            TokenKind.PIPE,
            TokenKind.COLON,
            TokenKind.DOT,
        }:
            self._advance()
            return a.Identifier(this=self._name_from_token(tok))
        raise self._err(f"mismatched input {tok.text!r}", code="CG1102")

    def parse_filter(self) -> a.Filter:
        self._expect(TokenKind.FILTER)
        self._expect(TokenKind.LPAREN)
        items: list[a.FilterItem] = []
        while True:
            var = self.parse_variable()
            self._expect(TokenKind.WHERE)
            pred = self.parse_expression()
            items.append(a.FilterItem(variable=var, predicate=pred))
            if not self._match(TokenKind.COMMA):
                break
        self._expect(TokenKind.RPAREN)
        return a.Filter(items=items)

    def parse_let(self) -> a.Let:
        self._expect(TokenKind.LET)
        items: list[a.AstNode] = []
        while True:
            var = self.parse_variable()
            self._expect(TokenKind.EQ)
            expr = self.parse_expression()
            items.append(a.Alias(this=expr, alias=var))
            if not self._match(TokenKind.COMMA):
                break
        return a.Let(items=items)

    def parse_for(self) -> a.For:
        self._expect(TokenKind.FOR)
        alias = self.parse_variable()
        self._expect(TokenKind.IN)
        expr = self.parse_expression()
        return a.For(expression=expr, alias=alias)

    def parse_load_csv(self) -> a.LoadCsv:
        self._expect_word("LOAD")
        self._expect_word("CSV")
        with_headers = False
        if self._match(TokenKind.WITH):
            self._expect_word("HEADERS")
            with_headers = True
        self._expect_word("FROM")
        url = self.parse_expression()
        self._expect(TokenKind.AS)
        alias = self.parse_variable()
        fieldterminator = None
        if self._match_word("FIELDTERMINATOR"):
            fieldterminator = self.parse_expression()
        return a.LoadCsv(
            url=url,
            alias=alias,
            with_headers=with_headers or None,
            fieldterminator=fieldterminator,
        )

    def parse_search(self) -> a.Search:
        self._expect_word("SEARCH")
        variable = self.parse_variable()
        self._expect(TokenKind.IN)
        self._expect(TokenKind.LPAREN)
        self._expect_word("VECTOR")
        self._expect(TokenKind.INDEX)
        index_name = self.parse_expression()
        self._expect(TokenKind.FOR)
        vector_expr = self.parse_expression()
        limit = None
        if self._match(TokenKind.LIMIT):
            limit = self.parse_expression()
        self._expect(TokenKind.RPAREN)
        score_alias = None
        if self._match_word("SCORE"):
            self._expect(TokenKind.AS)
            score_alias = self.parse_variable()
        return a.Search(
            variable=variable,
            index_name=index_name,
            vector_expr=vector_expr,
            limit=limit,
            score_alias=score_alias,
        )

    def parse_when_query(self) -> a.WhenQuery:
        branches: list[a.AstNode] = []
        while self._match(TokenKind.WHEN):
            cond = self.parse_expression()
            self._expect(TokenKind.THEN)
            self._expect(TokenKind.LBRACE)
            query = self.parse_statement()
            self._expect(TokenKind.RBRACE)
            branches.append(a.WhenBranch(condition=cond, query=query))
        default = None
        if self._match(TokenKind.ELSE):
            self._expect(TokenKind.LBRACE)
            default = self.parse_statement()
            self._expect(TokenKind.RBRACE)
        return a.WhenQuery(branches=branches, default=default)

    def parse_admin_statement(self) -> a.AdminStatement:
        """Capture the statement verbatim — admin DDL is passed through, not modelled.

        The source slice is kept because re-joining token text loses the original
        spacing, punctuation, and string quoting (``ON :Person(name)``).
        """
        start = self._peek().position.offset
        end = len(self.source)
        while not self._check(TokenKind.EOF):
            if self._check(TokenKind.RETURN):
                end = self._peek().position.offset
                break
            self._advance()
        return a.AdminStatement(text=self.source[start:end].strip())

    def _parse_group_by(self) -> a.GroupBy | None:
        if not (self._check_word("GROUP") and self._check_ahead(TokenKind.BY)):
            return None
        self._advance()
        if not self._dialect_allows("allow_group_by_subclause"):
            raise self._err("GROUP BY requires neo4j25 dialect", code="CG1102")
        self._expect(TokenKind.BY)
        return a.GroupBy(expressions=self.parse_return_items())

    def _dialect_allows(self, flag: str) -> bool:
        if not self.dialect:
            return True
        from cypherast.dialects.dialect import get_dialect_cls

        caps = get_dialect_cls(self.dialect).capabilities
        return bool(getattr(caps, flag, False))

    def _peek_ahead_text(self, n: int) -> str:
        return self._peek(n).text.upper()

    # --- contextual words -------------------------------------------------
    # Words Neo4j does not reserve (LOAD, CSV, GROUP, ROWS, SEARCH, …) stay IDENT so
    # they remain usable as variables and property names; clause parsers match them
    # by text instead of by TokenKind.

    def _check_word(self, word: str, n: int = 0) -> bool:
        tok = self._peek(n)
        return tok.kind is TokenKind.IDENT and tok.text.upper() == word

    def _match_word(self, word: str) -> bool:
        if self._check_word(word):
            self._advance()
            return True
        return False

    def _expect_word(self, word: str) -> Token:
        if self._check_word(word):
            return self._advance()
        tok = self._peek()
        raise self._err(
            f"mismatched input {tok.text!r}",
            code="CG1102",
            expected={word},
        )

    # --- token helpers ----------------------------------------------------

    def _peek(self, n: int = 0) -> Token:
        j = self._i + n
        if j >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[j]

    def _check(self, kind: TokenKind) -> bool:
        return self._peek().kind is kind

    def _check_any(self, *kinds: TokenKind) -> bool:
        return self._peek().kind in kinds

    def _check_ahead(self, kind: TokenKind, n: int = 1) -> bool:
        return self._peek(n).kind is kind

    def _match(self, kind: TokenKind) -> bool:
        if self._check(kind):
            self._advance()
            return True
        return False

    def _advance(self) -> Token:
        tok = self._peek()
        if tok.kind is not TokenKind.EOF:
            self._i += 1
        return tok

    def _expect(self, kind: TokenKind) -> Token:
        if self._check(kind):
            return self._advance()
        tok = self._peek()
        raise self._err(
            f"mismatched input {tok.text!r}",
            code="CG1102",
            expected={kind.name},
        )

    # --- nesting guard ----------------------------------------------------

    @contextmanager
    def _nesting(self) -> Iterator[None]:
        self._depth += 1
        try:
            if self._depth > self.max_depth:
                raise _ParseDepthExceeded
            yield
        finally:
            self._depth -= 1

    def _depth_error(self) -> ParseError:
        return ParseError(
            "maximum recursion depth exceeded while parsing",
            code="CG1105",
            position=self._peek().position,
            hint=(
                f"reduce query nesting (MAX_PARSE_DEPTH={self.max_depth}; "
                "the interpreter stack can trip sooner)"
            ),
        )

    def _err(
        self,
        message: str,
        *,
        code: str,
        expected: set[str] | None = None,
    ) -> ParseError:
        tok = self._peek()
        return ParseError(
            message,
            code=code,
            position=tok.position if tok else Position(),
            source=self.source,
            expected=expected,
        )
