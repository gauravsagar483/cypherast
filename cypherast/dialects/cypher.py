"""Shared Cypher dialect base: inheritance root for concrete Cypher engines."""

from __future__ import annotations

import typing as t

from cypherast import ast as a
from cypherast.dialects.capabilities import DEFAULT_CYPHER_CAPABILITIES, DialectCapabilities
from cypherast.dialects.dialect import Dialect
from cypherast.errors import CompatibilityError
from cypherast.renderer import Renderer

GQL_DDL_NODES: frozenset[type[a.AstNode]] = frozenset(
    {
        a.CreateGraphType,
        a.GraphTypeRef,
        a.SessionCommand,
        a.TransactionCommand,
        a.BindingTable,
        a.ValueTable,
    }
)

DEFAULT_UNSUPPORTED_GQL: frozenset[type[a.AstNode]] = frozenset(
    {
        a.Next,
        a.Insert,
        a.Use,
        *GQL_DDL_NODES,
        a.QuantifiedPath,
    }
)

# Nodes a dialect may only render when it declares the matching capability, so
# transpiling toward an engine that cannot express them raises instead of emitting
# text that engine would reject.
CAPABILITY_GATED_NODES: dict[type[a.AstNode], str] = {
    a.Filter: "allow_filter_clause",
    a.For: "allow_for_clause",
    a.Let: "allow_let_clause",
    a.GroupBy: "allow_group_by_subclause",
    a.Search: "allow_search_clause",
    a.WhenQuery: "allow_when_query",
    a.WhenBranch: "allow_when_query",
    a.LoadCsv: "allow_load_csv",
    a.AdminStatement: "allow_admin_ddl",
    a.RelationshipLambda: "allow_memgraph_rel_quantifiers",
}


def build_unsupported(
    capabilities: DialectCapabilities,
    *,
    quantified_path: bool = False,
    use_clause: bool = False,
    insert_clause: bool = False,
    next_clause: bool = False,
    extra: frozenset[type[a.AstNode]] = frozenset(),
) -> set[type[a.AstNode]]:
    """Build a renderer ``unsupported`` set from ``capabilities`` plus GQL flags.

    ``quantified_path`` stays separate from ``reject_quantified_path``: openCypher
    renders quantified paths and only rejects them during strict validation.
    """
    blocked: set[type[a.AstNode]] = set(GQL_DDL_NODES) | set(extra)
    blocked |= {
        node for node, flag in CAPABILITY_GATED_NODES.items() if not getattr(capabilities, flag)
    }
    if not quantified_path:
        blocked.add(a.QuantifiedPath)
    if not use_clause:
        blocked.add(a.Use)
    if not insert_clause:
        blocked.add(a.Insert)
    if not next_clause:
        blocked.add(a.Next)
    return blocked


class CypherRenderer(Renderer):
    """Cypher renderer with dialect hooks for pattern predicates and unsupported nodes."""

    dialect_name: str = "cypher"
    pattern_predicate_style: t.ClassVar[t.Literal["exists", "bare"]] = "exists"
    capabilities: t.ClassVar[DialectCapabilities] = DEFAULT_CYPHER_CAPABILITIES
    unsupported: set[type[a.AstNode]] = build_unsupported(DEFAULT_CYPHER_CAPABILITIES)

    def render_RelationshipPattern(self, node: a.RelationshipPattern) -> str:
        # Quantifiers live on the pattern, so the ``unsupported`` node set cannot gate
        # them; a bare ``*bfs`` would otherwise render into a dialect without it.
        if node.memgraph_quantifier and not self.capabilities.allow_memgraph_rel_quantifiers:
            raise CompatibilityError(
                f"Relationship quantifier '*{node.memgraph_quantifier}' is not supported "
                f"by dialect {self.dialect_name!r}",
                code="CG1401",
                hint="Target dialect 'memgraph' for *bfs / *wShortest",
            )
        return super().render_RelationshipPattern(node)

    def render_PatternPredicate(self, node: a.PatternPredicate) -> str:
        body = self.dispatch(node.pattern)
        if isinstance(node.pattern, (a.Query, a.Union, a.Cypher, a.WhenQuery)):
            text = f"EXISTS {{ {body} }}"
            return f"NOT {text}" if node.not_ else text
        if isinstance(node.pattern, a.PathPattern):
            if self.pattern_predicate_style == "bare":
                return f"NOT ({body})" if node.not_ else f"({body})"
            return f"NOT EXISTS ({body})" if node.not_ else f"EXISTS ({body})"
        return f"NOT {body}" if node.not_ else body


class CypherDialect(Dialect):
    """Permissive Cypher base; Neo4j / Memgraph / openCypher subclass from here."""

    capabilities: t.ClassVar[DialectCapabilities] = DEFAULT_CYPHER_CAPABILITIES
    renderer_cls: t.ClassVar[type[Renderer]] = CypherRenderer

    @classmethod
    def renderer(cls) -> Renderer:
        return cls.renderer_cls()
