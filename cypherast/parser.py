"""Recursive-descent Cypher/GQL parser (tokens -> IR)."""

from __future__ import annotations

import typing as t

from cypherast import ast as a
from cypherast.errors import ParseError, Position
from cypherast.lexer import Lexer, Token, TokenKind


class Parser:
    """Handwritten recursive-descent parser for openCypher core (+ Neo4j/GQL tolerant bits)."""

    def __init__(self, source: str, dialect: str | None = None) -> None:
        self.source = source
        self.dialect = dialect
        self.tokens = Lexer(source).tokenize()
        self._i = 0

    # --- public -----------------------------------------------------------

    def parse(self) -> a.AstNode:
        node = self.parse_statement()
        if not self._check(TokenKind.EOF):
            tok = self._peek()
            raise self._err(
                f"Unexpected token {tok.text!r}",
                code="CG1101",
                expected={"EOF"},
            )
        return a.Cypher(this=node)

    def parse_statement(self) -> a.AstNode:
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
            if self._check(TokenKind.OPTIONAL) or self._check(TokenKind.MATCH):
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
            elif self._check(TokenKind.CALL):
                clauses.append(self.parse_call_subquery())
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
        where = None
        if self._match(TokenKind.WHERE):
            where = a.Where(this=self.parse_expression())
        return a.Match(pattern=pattern, optional=optional or None, where=where)

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
        )

    def parse_return(self) -> a.Return:
        self._expect(TokenKind.RETURN)
        distinct = self._match(TokenKind.DISTINCT)
        exprs = self.parse_return_items()
        order = self.parse_order_by() if self._check(TokenKind.ORDER) else None
        skip = a.Skip(this=self.parse_expression()) if self._match(TokenKind.SKIP) else None
        limit = a.Limit(this=self.parse_expression()) if self._match(TokenKind.LIMIT) else None
        return a.Return(
            expressions=exprs,
            distinct=distinct or None,
            order=order,
            skip=skip,
            limit=limit,
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
            items.append(a.Ordered(this=expr, desc=desc or None))
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
            op = "="
            if self._match(TokenKind.PLUS):
                self._expect(TokenKind.EQ)
                op = "+="
            else:
                self._expect(TokenKind.EQ)
            right = self.parse_expression()
            items.append(a.SetItem(this=left, expression=right, op=op if op != "=" else None))
            if not self._match(TokenKind.COMMA):
                break
        return a.Set(items=items)

    def parse_set_target(self) -> a.AstNode:
        """SET LHS: property / variable / labels — must not consume ``=`` as comparison."""
        node = self.parse_postfix()
        if self._check(TokenKind.COLON) and isinstance(node, a.Identifier):
            labels = self._parse_labels()
            return a.NodePattern(variable=node, labels=labels)
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
            # REMOVE n.prop  OR  REMOVE n:Label:Label2
            target = self.parse_postfix()
            if self._check(TokenKind.COLON) and isinstance(target, a.Identifier):
                labels = self._parse_labels()
                items.append(a.NodePattern(variable=target, labels=labels))
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

    def parse_call_subquery(self) -> a.CallSubquery:
        """Parse ``CALL { query }`` (Neo4j subquery form; parse-tolerant)."""
        self._expect(TokenKind.CALL)
        self._expect(TokenKind.LBRACE)
        inner = self.parse_statement()
        self._expect(TokenKind.RBRACE)
        return a.CallSubquery(query=inner)

    # --- patterns ---------------------------------------------------------

    def parse_pattern(self) -> a.Pattern:
        paths = [self.parse_path_pattern()]
        while self._match(TokenKind.COMMA):
            paths.append(self.parse_path_pattern())
        return a.Pattern(paths=paths)

    def parse_path_pattern(self) -> a.PathPattern:
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
        if (
            self._check(TokenKind.LPAREN)
            and self._peek(1).kind is TokenKind.LPAREN
        ):
            saved = self._i
            self._advance()  # outer (
            try:
                inner = self.parse_path_pattern()
                self._expect(TokenKind.RPAREN)
                if self._check(TokenKind.LBRACE) or self._check(TokenKind.STAR) or self._check(
                    TokenKind.PLUS
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
        self._expect(TokenKind.RPAREN)
        return a.NodePattern(variable=variable, labels=labels, properties=properties)

    def _parse_labels(self) -> a.LabelExpression:
        labels: list[str] = []
        while self._match(TokenKind.COLON):
            if not self._check(TokenKind.IDENT):
                raise self._err("Expected label name", code="CG1104")
            labels.append(self._advance().text)
        return a.LabelExpression(labels=labels)

    def parse_relationship_pattern(self) -> a.RelationshipPattern:
        direction = a.Direction.BOTH
        if self._match(TokenKind.ARROW_LEFT):
            direction = a.Direction.INCOMING
            # <-[...]-  or  <--
            if self._check(TokenKind.LBRACKET):
                rel = self._parse_rel_detail(direction)
                self._expect(TokenKind.MINUS)
                return rel
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
        # anonymous undirected --
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
            types = [self._expect(TokenKind.IDENT).text]
            while self._match(TokenKind.PIPE):
                # optional colon before next type
                self._match(TokenKind.COLON)
                types.append(self._expect(TokenKind.IDENT).text)
        if self._match(TokenKind.STAR):
            variable_length = True
            if self._check(TokenKind.INTEGER):
                min_hops = int(self._advance().text)
                if self._match(TokenKind.DOTDOT):
                    max_hops = (
                        int(self._advance().text) if self._check(TokenKind.INTEGER) else None
                    )
                else:
                    max_hops = min_hops
            elif self._match(TokenKind.DOTDOT):
                min_hops = 1
                if self._check(TokenKind.INTEGER):
                    max_hops = int(self._advance().text)
            else:
                min_hops = 1
                max_hops = None
        if self._check(TokenKind.LBRACE):
            properties = self.parse_map_literal()
        self._expect(TokenKind.RBRACKET)
        return a.RelationshipPattern(
            variable=variable,
            types=types,
            properties=properties,
            direction=direction,
            min_hops=min_hops,
            max_hops=max_hops,
            variable_length=variable_length or None,
        )

    # --- expressions (Pratt-ish precedence climbing) ----------------------

    def parse_expression(self) -> a.AstNode:
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
            # Pattern predicate: NOT (n)-[:R]->()
            if self._check(TokenKind.LPAREN) and self._looks_like_pattern_start():
                return a.PatternPredicate(pattern=self.parse_path_pattern(), not_=True)
            return a.Not(this=self.parse_not())
        # EXISTS { … } / EXISTS (pattern) handled in primary
        return self.parse_comparison()

    def _looks_like_pattern_start(self) -> bool:
        """True if ``(`` begins a node pattern rather than a parenthesized expression."""
        # Peek: ( IDENT? :? or ( ) or ( {
        if not self._check(TokenKind.LPAREN):
            return False
        n1 = self._peek(1).kind
        n2 = self._peek(2).kind
        if n1 in (TokenKind.COLON, TokenKind.RPAREN, TokenKind.LBRACE):
            return True
        return n1 is TokenKind.IDENT and n2 in (
            TokenKind.COLON,
            TokenKind.RPAREN,
            TokenKind.LBRACE,
            TokenKind.MINUS,
            TokenKind.ARROW_LEFT,
            TokenKind.ARROW_RIGHT,
        )

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
                name = self._expect(TokenKind.IDENT).text
                node = a.Property(this=node, name=name)
                if self._check(TokenKind.LBRACE):
                    entries = self._parse_map_projection_entries()
                    node = a.MapProjection(this=node, entries=entries)
            elif self._check(TokenKind.LBRACE) and isinstance(node, a.Identifier):
                entries = self._parse_map_projection_entries()
                node = a.MapProjection(this=node, entries=entries)
            elif self._match(TokenKind.LBRACKET):
                # list/string subscript: expr[index]
                index = self.parse_expression()
                self._expect(TokenKind.RBRACKET)
                node = a.ListSubscript(this=node, index=index)
            else:
                break
        return node

    def parse_primary(self) -> a.AstNode:
        tok = self._peek()
        if tok.kind is TokenKind.INTEGER:
            self._advance()
            return a.Integer(this=int(tok.text))
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
        if tok.kind is TokenKind.LPAREN:
            # Could be parenthesized expr OR a pattern (node) in expression context
            return self._parse_paren_or_pattern()
        # Function call or identifier
        if tok.kind is TokenKind.IDENT or tok.kind in (
            TokenKind.COUNT,
            TokenKind.COLLECT,
            TokenKind.SHORTESTPATH,
            TokenKind.ALLSHORTESTPATHS,
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
            if self._match(TokenKind.LPAREN):
                distinct = self._match(TokenKind.DISTINCT)
                if self._match(TokenKind.STAR) and name.lower() == "count":
                    self._expect(TokenKind.RPAREN)
                    return a.FunctionCall(name="count", expressions=[a.Star()], distinct=None)
                args: list[a.AstNode] = []
                if not self._check(TokenKind.RPAREN):
                    args = self.parse_expression_list()
                self._expect(TokenKind.RPAREN)
                if name.lower() == "coalesce":
                    return a.Coalesce(expressions=args)
                return a.FunctionCall(
                    name=name, expressions=args, distinct=distinct or None
                )
            return a.Identifier(this=name)
        raise self._err(f"Unexpected token {tok.text!r}", code="CG1101")

    def parse_exists(self) -> a.AstNode:
        """``EXISTS { query }`` or ``EXISTS ( pattern )`` / ``exists(expr)``."""
        self._expect(TokenKind.EXISTS)
        if self._match(TokenKind.LBRACE):
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
        # Pattern predicate (no extra outer wrap): WHERE (n)-[:R]->(:L)
        if self._looks_like_pattern_start():
            saved = self._i
            try:
                path = self.parse_path_pattern()
                # Relationship path → pattern predicate (same as NOT (path))
                if len(path.elements) > 1:
                    self._match(TokenKind.RPAREN)  # optional ((path))
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
                    self._match(TokenKind.RPAREN)
                    return a.PatternPredicate(pattern=path, not_=False)
                self._i = saved
            except ParseError:
                self._i = saved

        self._expect(TokenKind.LPAREN)
        # Heuristic: if we see a node pattern shape, try pattern / (n) unwrap
        if self._check(TokenKind.IDENT) or self._check(TokenKind.COLON) or self._check(
            TokenKind.RPAREN
        ) or self._check(TokenKind.LBRACE):
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
        # Pattern comprehension: [(n)-->(m) | m.x]
        if self._check(TokenKind.LPAREN):
            saved = self._i
            try:
                path = self.parse_path_pattern()
                where: a.Where | None = (
                    a.Where(this=self.parse_expression()) if self._match(TokenKind.WHERE) else None
                )
                if self._match(TokenKind.PIPE):
                    proj = self.parse_expression()
                    self._expect(TokenKind.RBRACKET)
                    return a.PatternComprehension(
                        pattern=path, where=where, projection=proj
                    )
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
                key = self._expect(TokenKind.IDENT).text
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
                if self._match(TokenKind.DOT) and self._match(TokenKind.STAR):
                    entries.append(a.Star())
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
        tok = self._expect(TokenKind.IDENT)
        return a.Identifier(this=tok.text)

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
