"""IR -> Cypher text renderer (openCypher Style Guide formatting)."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.errors import CompatibilityError


class Renderer:
    """Base renderer. Dialects subclass and override unsupported nodes."""

    dialect_name: str = "opencypher"
    unsupported: set[type[a.AstNode]] = {
        a.Next,
        a.Insert,
        a.CreateGraphType,
        a.GraphTypeRef,
        a.SessionCommand,
        a.TransactionCommand,
        a.BindingTable,
        a.ValueTable,
        a.Use,
        a.Yield,
        a.QuantifiedPath,
    }

    def generate(self, node: a.AstNode, pretty: bool = False) -> str:
        self._pretty = pretty
        self._indent = 0
        return self.dispatch(node)

    def dispatch(self, node: a.AstNode | None) -> str:
        if node is None:
            return ""
        typ = type(node)
        if typ in self.unsupported:
            raise CompatibilityError(
                f"{typ.__name__} is not supported by dialect {self.dialect_name!r}",
                code="CG1401",
                hint=f"Target dialect '{self.dialect_name}' cannot express {typ.__name__}",
            )
        method = getattr(self, f"render_{typ.__name__}", None)
        if method is None:
            raise CompatibilityError(
                f"No renderer for {typ.__name__}",
                code="CG1401",
            )
        return str(method(node))

    # --- top-level --------------------------------------------------------

    def render_Cypher(self, node: a.Cypher) -> str:
        return self.dispatch(node.this)

    def render_Query(self, node: a.Query) -> str:
        sep = "\n" if self._pretty else " "
        return sep.join(self.dispatch(c) for c in node.clauses)

    def render_Union(self, node: a.Union) -> str:
        kw = "UNION" if node.distinct else "UNION ALL"
        sep = f"\n{kw}\n" if self._pretty else f" {kw} "
        return self.dispatch(node.this) + sep + self.dispatch(node.expression)

    def render_Next(self, node: a.Next) -> str:
        sep = "\nNEXT\n" if self._pretty else " NEXT "
        return self.dispatch(node.this) + sep + self.dispatch(node.expression)

    # --- clauses ----------------------------------------------------------

    def render_Match(self, node: a.Match) -> str:
        parts = []
        if node.optional:
            parts.append("OPTIONAL MATCH")
        else:
            parts.append("MATCH")
        parts.append(self.dispatch(node.pattern))
        body = " ".join(parts)
        if node.where:
            sep = "\n" if self._pretty else " "
            body += sep + self.dispatch(node.where)
        return body

    def render_Where(self, node: a.Where) -> str:
        return f"WHERE {self.dispatch(node.this)}"

    def render_With(self, node: a.With) -> str:
        parts = ["WITH"]
        if node.distinct:
            parts.append("DISTINCT")
        parts.append(self._proj_list(node.expressions))
        body = " ".join(parts)
        body += self._tail(node)
        if node.where:
            sep = "\n" if self._pretty else " "
            body += sep + self.dispatch(node.where)
        return body

    def render_Return(self, node: a.Return) -> str:
        parts = ["RETURN"]
        if node.distinct:
            parts.append("DISTINCT")
        parts.append(self._proj_list(node.expressions))
        body = " ".join(parts)
        body += self._tail(node)
        return body

    def _tail(self, node: a.AstNode) -> str:
        bits: list[str] = []
        if getattr(node, "order", None):
            bits.append(self.dispatch(node.order))
        if getattr(node, "skip", None):
            bits.append(self.dispatch(node.skip))
        if getattr(node, "limit", None):
            bits.append(self.dispatch(node.limit))
        if not bits:
            return ""
        sep = "\n" if self._pretty else " "
        return sep + sep.join(bits)

    def _proj_list(self, exprs: list[a.AstNode]) -> str:
        return ", ".join(self.dispatch(e) for e in exprs)

    def render_Unwind(self, node: a.Unwind) -> str:
        return f"UNWIND {self.dispatch(node.expression)} AS {self.dispatch(node.alias)}"

    def render_Order(self, node: a.Order) -> str:
        return "ORDER BY " + ", ".join(self.dispatch(e) for e in node.expressions)

    def render_Ordered(self, node: a.Ordered) -> str:
        s = self.dispatch(node.this)
        return f"{s} DESC" if node.desc else s

    def render_Skip(self, node: a.Skip) -> str:
        return f"SKIP {self.dispatch(node.this)}"

    def render_Limit(self, node: a.Limit) -> str:
        return f"LIMIT {self.dispatch(node.this)}"

    def render_Create(self, node: a.Create) -> str:
        return f"CREATE {self.dispatch(node.pattern)}"

    def render_Insert(self, node: a.Insert) -> str:
        return f"INSERT {self.dispatch(node.pattern)}"

    def render_Merge(self, node: a.Merge) -> str:
        body = f"MERGE {self.dispatch(node.pattern)}"
        if node.actions:
            sep = "\n" if self._pretty else " "
            for action in node.actions:
                body += sep + self.dispatch(action)
        return body

    def render_OnCreate(self, node: a.OnCreate) -> str:
        return "ON CREATE " + " ".join(self.dispatch(x) for x in node.actions)

    def render_OnMatch(self, node: a.OnMatch) -> str:
        return "ON MATCH " + " ".join(self.dispatch(x) for x in node.actions)

    def render_Set(self, node: a.Set) -> str:
        return "SET " + ", ".join(self.dispatch(i) for i in node.items)

    def render_SetItem(self, node: a.SetItem) -> str:
        op = node.op or "="
        return f"{self.dispatch(node.this)} {op} {self.dispatch(node.expression)}"

    def render_Delete(self, node: a.Delete) -> str:
        kw = "DETACH DELETE" if node.detach else "DELETE"
        return f"{kw} " + ", ".join(self.dispatch(e) for e in node.expressions)

    def render_Remove(self, node: a.Remove) -> str:
        return "REMOVE " + ", ".join(self.dispatch(i) for i in node.items)

    def render_Foreach(self, node: a.Foreach) -> str:
        body = " ".join(self.dispatch(c) for c in node.clauses)
        return (
            f"FOREACH ({self.dispatch(node.variable)} IN {self.dispatch(node.expression)}"
            f" | {body})"
        )

    def render_CallSubquery(self, node: a.CallSubquery) -> str:
        return f"CALL {{ {self.dispatch(node.query)} }}"

    def render_Use(self, node: a.Use) -> str:
        return f"USE {self.dispatch(node.graph)}"

    def render_Yield(self, node: a.Yield) -> str:
        return "YIELD " + self._proj_list(node.expressions)

    def render_Placeholder(self, node: a.Placeholder) -> str:
        return str(node.name or "?")

    # --- patterns ---------------------------------------------------------

    def render_Pattern(self, node: a.Pattern) -> str:
        return ", ".join(self.dispatch(p) for p in node.paths)

    def render_PathPattern(self, node: a.PathPattern) -> str:
        body = "".join(self.dispatch(e) for e in node.elements)
        if node.variable:
            return f"{self.dispatch(node.variable)} = {body}"
        return body

    def render_NodePattern(self, node: a.NodePattern) -> str:
        parts: list[str] = []
        if node.variable:
            parts.append(self.dispatch(node.variable))
        if node.labels:
            parts.append(self.dispatch(node.labels))
        if node.properties:
            parts.append(self.dispatch(node.properties))
        return "(" + "".join(parts) + ")"

    def render_LabelExpression(self, node: a.LabelExpression) -> str:
        if node.expression:
            return f":{node.expression}"
        return "".join(f":{lab}" for lab in (node.labels or []))

    def render_RelationshipPattern(self, node: a.RelationshipPattern) -> str:
        inner_parts: list[str] = []
        if node.variable:
            inner_parts.append(self.dispatch(node.variable))
        if node.types:
            inner_parts.append(":" + "|".join(node.types))
        if node.variable_length:
            star = "*"
            if node.min_hops is not None and node.max_hops is not None:
                if node.min_hops == node.max_hops:
                    star += str(node.min_hops)
                else:
                    star += f"{node.min_hops}..{node.max_hops}"
            elif node.min_hops is not None:
                star += f"{node.min_hops}.."
            elif node.max_hops is not None:
                star += f"..{node.max_hops}"
            inner_parts.append(star)
        if node.properties:
            inner_parts.append(self.dispatch(node.properties))
        detail = "".join(inner_parts)
        bracketed = f"[{detail}]" if detail or node.variable_length or node.types or node.properties or node.variable else ""
        d = node.direction
        if d is a.Direction.OUTGOING:
            return f"-{bracketed}->" if bracketed else "-->"
        if d is a.Direction.INCOMING:
            return f"<-{bracketed}-" if bracketed else "<--"
        return f"-{bracketed}-" if bracketed else "--"

    def render_ShortestPath(self, node: a.ShortestPath) -> str:
        name = "allShortestPaths" if node.all_ else "shortestPath"
        return f"{name}({self.dispatch(node.this)})"

    # --- expressions ------------------------------------------------------

    def render_Alias(self, node: a.Alias) -> str:
        return f"{self.dispatch(node.this)} AS {self.dispatch(node.alias)}"

    def render_Star(self, node: a.Star) -> str:
        return "*"

    def render_Identifier(self, node: a.Identifier) -> str:
        return str(node.this)

    def render_Property(self, node: a.Property) -> str:
        return f"{self.dispatch(node.this)}.{node.name}"

    def render_Parameter(self, node: a.Parameter) -> str:
        return f"${node.name}"

    def render_Null(self, node: a.Null) -> str:
        return "null"

    def render_Boolean(self, node: a.Boolean) -> str:
        return "true" if node.this else "false"

    def render_Integer(self, node: a.Integer) -> str:
        return str(node.this)

    def render_Float(self, node: a.Float) -> str:
        return str(node.this)

    def render_String(self, node: a.String) -> str:
        escaped = (
            node.this.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f"'{escaped}'"

    def render_List(self, node: a.List) -> str:
        return "[" + ", ".join(self.dispatch(e) for e in node.expressions) + "]"

    def render_ListSubscript(self, node: a.ListSubscript) -> str:
        return f"{self.dispatch(node.this)}[{self.dispatch(node.index)}]"

    def render_PatternPredicate(self, node: a.PatternPredicate) -> str:
        body = self.dispatch(node.pattern)
        if isinstance(node.pattern, (a.Query, a.Union, a.Cypher)):
            text = f"EXISTS {{ {body} }}"
            return f"NOT {text}" if node.not_ else text
        if isinstance(node.pattern, a.PathPattern):
            # Keep openCypher pattern-predicate form. Do NOT wrap NOT-patterns as
            # EXISTS(...) — engines (incl. PuppyGraph) reject that / lack exists().
            if node.not_:
                return f"NOT ({body})"
            return f"EXISTS ({body})"
        return f"NOT {body}" if node.not_ else body

    def render_QuantifiedPath(self, node: a.QuantifiedPath) -> str:
        body = self.dispatch(node.this)
        lo = "" if node.min_hops is None else str(node.min_hops)
        hi = "" if node.max_hops is None else str(node.max_hops)
        return f"({body}){{{lo},{hi}}}"

    def render_Map(self, node: a.Map) -> str:
        parts = [f"{k}: {self.dispatch(v)}" for k, v in node.entries]
        return "{" + ", ".join(parts) + "}"

    def render_MapProjection(self, node: a.MapProjection) -> str:
        parts: list[str] = []
        for e in node.entries:
            if isinstance(e, a.Star):
                parts.append(".*")
            elif isinstance(e, tuple):
                parts.append(f"{e[0]}: {self.dispatch(e[1])}")
            else:
                parts.append(str(e))
        return f"{self.dispatch(node.this)}{{{', '.join(parts)}}}"

    def _bin(self, node: a.Binary, op: str) -> str:
        return f"{self.dispatch(node.this)} {op} {self.dispatch(node.expression)}"

    def render_Add(self, node: a.Add) -> str:
        return self._bin(node, "+")

    def render_Sub(self, node: a.Sub) -> str:
        return self._bin(node, "-")

    def render_Mul(self, node: a.Mul) -> str:
        return self._bin(node, "*")

    def render_Div(self, node: a.Div) -> str:
        return self._bin(node, "/")

    def render_Mod(self, node: a.Mod) -> str:
        return self._bin(node, "%")

    def render_Pow(self, node: a.Pow) -> str:
        return self._bin(node, "^")

    def render_EQ(self, node: a.EQ) -> str:
        return self._bin(node, "=")

    def render_NEQ(self, node: a.NEQ) -> str:
        return self._bin(node, "<>")

    def render_LT(self, node: a.LT) -> str:
        return self._bin(node, "<")

    def render_LTE(self, node: a.LTE) -> str:
        return self._bin(node, "<=")

    def render_GT(self, node: a.GT) -> str:
        return self._bin(node, ">")

    def render_GTE(self, node: a.GTE) -> str:
        return self._bin(node, ">=")

    def render_And(self, node: a.And) -> str:
        return self._bin(node, "AND")

    def render_Or(self, node: a.Or) -> str:
        return self._bin(node, "OR")

    def render_Xor(self, node: a.Xor) -> str:
        return self._bin(node, "XOR")

    def render_In(self, node: a.In) -> str:
        return self._bin(node, "IN")

    def render_StartsWith(self, node: a.StartsWith) -> str:
        return self._bin(node, "STARTS WITH")

    def render_EndsWith(self, node: a.EndsWith) -> str:
        return self._bin(node, "ENDS WITH")

    def render_Contains(self, node: a.Contains) -> str:
        return self._bin(node, "CONTAINS")

    def render_Not(self, node: a.Not) -> str:
        return f"NOT {self.dispatch(node.this)}"

    def render_Neg(self, node: a.Neg) -> str:
        return f"-{self.dispatch(node.this)}"

    def render_IsNull(self, node: a.IsNull) -> str:
        return f"{self.dispatch(node.this)} IS{' NOT' if node.not_ else ''} NULL"

    def render_FunctionCall(self, node: a.FunctionCall) -> str:
        distinct = "DISTINCT " if node.distinct else ""
        args = ", ".join(self.dispatch(e) for e in node.expressions)
        return f"{node.name}({distinct}{args})"

    def render_Coalesce(self, node: a.Coalesce) -> str:
        args = ", ".join(self.dispatch(e) for e in node.expressions)
        return f"coalesce({args})"

    def render_Case(self, node: a.Case) -> str:
        parts = ["CASE"]
        if node.this:
            parts.append(self.dispatch(node.this))
        for cond, then in node.ifs:
            parts.append(f"WHEN {self.dispatch(cond)} THEN {self.dispatch(then)}")
        if node.default:
            parts.append(f"ELSE {self.dispatch(node.default)}")
        parts.append("END")
        return " ".join(parts)

    def render_ListComprehension(self, node: a.ListComprehension) -> str:
        body = f"{self.dispatch(node.variable)} IN {self.dispatch(node.source)}"
        if node.where:
            body += f" WHERE {self.dispatch(node.where)}"
        if node.projection:
            body += f" | {self.dispatch(node.projection)}"
        return f"[{body}]"

    def render_PatternComprehension(self, node: a.PatternComprehension) -> str:
        body = self.dispatch(node.pattern)
        if node.where:
            body += f" WHERE {self.dispatch(node.where.this if isinstance(node.where, a.Where) else node.where)}"
        body += f" | {self.dispatch(node.projection)}"
        return f"[{body}]"