"""Binding-level lineage / provenance."""

from __future__ import annotations

import json
import typing as t
from dataclasses import dataclass, field

from cypherast import ast as a
from cypherast.errors import ValidationError
from cypherast.scope import Scope, build_scope


@dataclass
class Node:
    name: str
    expression: a.AstNode
    source: a.AstNode
    downstream: list[Node] = field(default_factory=list)
    source_name: str = ""
    reference_node_name: str = ""
    payload: dict[str, t.Any] = field(default_factory=dict)

    def walk(self) -> t.Iterator[Node]:
        seen: set[int] = set()
        queue = [self]
        while queue:
            n = queue.pop()
            i = id(n)
            if i in seen:
                continue
            seen.add(i)
            yield n
            queue.extend(reversed(n.downstream))

    def to_html(self, **opts: t.Any) -> GraphHTML:
        nodes: dict[int, dict[str, t.Any]] = {}
        edges: list[dict[str, int]] = []
        for n in self.walk():
            try:
                label = n.expression.cypher(pretty=True)
            except Exception:
                label = n.name
            nodes[id(n)] = {
                "id": id(n),
                "label": label[:80],
                "title": f"<pre>{label}</pre>",
                "group": 0,
            }
            for d in n.downstream:
                edges.append({"from": id(n), "to": id(d)})
        return GraphHTML(nodes, edges, **opts)


class GraphHTML:
    def __init__(
        self,
        nodes: dict[int, dict[str, t.Any]],
        edges: list[dict[str, int]],
        imports: bool = True,
        options: dict[str, t.Any] | None = None,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.imports = imports
        self.options = {
            "height": "500px",
            "width": "100%",
            "layout": {"hierarchical": {"enabled": True, "sortMethod": "directed"}},
            "edges": {"arrows": "to"},
            **(options or {}),
        }

    def __str__(self) -> str:
        imports = (
            """<script src="https://unpkg.com/vis-data@latest/peer/umd/vis-data.min.js"></script>
<script src="https://unpkg.com/vis-network@latest/peer/umd/vis-network.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/vis-network/styles/vis-network.min.css"/>"""
            if self.imports
            else ""
        )
        return f"""<div>
<div id="cypherast-lineage"></div>
{imports}
<script>
new vis.Network(
  document.getElementById("cypherast-lineage"),
  {{nodes: new vis.DataSet({json.dumps(list(self.nodes.values()))}),
    edges: new vis.DataSet({json.dumps(self.edges)})}},
  {json.dumps(self.options)}
);
</script>
</div>"""

    def _repr_html_(self) -> str:
        return str(self)


def lineage(
    tree: a.AstNode,
    binding: str | None = None,
    *,
    schema: object | None = None,
    sources: dict[str, a.AstNode] | None = None,
    scope: Scope | None = None,
    on_node: t.Callable[[Node], None] | None = None,
) -> Node | dict[str, Node]:
    """Trace RETURN bindings back to pattern properties / variables / literals."""
    scope = scope or build_scope(tree)
    query = tree.this if isinstance(tree, a.Cypher) else tree
    ret = _find_return(query)
    if ret is None:
        raise ValidationError("Cannot build lineage without RETURN", code="CG1203")

    projections = _named_projections(ret)
    if binding is not None:
        if binding not in projections:
            raise ValidationError(
                f"Cannot find binding {binding!r} in RETURN",
                code="CG1203",
            )
        expr = _resolve_through_with(projections[binding], query, ret=ret)
        return _to_node(binding, expr, ret, on_node=on_node)

    return {
        name: _to_node(name, _resolve_through_with(expr, query, ret=ret), ret, on_node=on_node)
        for name, expr in projections.items()
    }


def _resolve_through_with(
    expr: a.AstNode,
    query: a.AstNode,
    *,
    ret: a.Return | None = None,
) -> a.AstNode:
    """Follow RETURN identifiers to defining expressions on preceding WITH aliases.

    Resolution walks backwards from the RETURN so a later WITH shadows an earlier
    alias of the same name. Each hop searches only clauses before the definition
    it just used, and repeated names stop the walk, so ``WITH n AS n`` and alias
    cycles terminate with the last useful expression.

    Core-only: surface ``Let`` is not consulted — callers must lower first.
    """
    if not isinstance(expr, a.Identifier):
        return expr
    if isinstance(query, a.Union):
        # Prefer left branch definitions for simple UNION lineage.
        left = query.this
        return _resolve_through_with(expr, left, ret=_find_return(left))
    if not isinstance(query, a.Query):
        return expr

    clauses = list(query.clauses or [])
    index = _clause_index(clauses, ret) if ret is not None else len(clauses)
    current: a.AstNode = expr
    seen: set[str] = set()
    while isinstance(current, a.Identifier):
        name = str(current.this)
        if name in seen:
            return current
        seen.add(name)
        found = _nearest_definition(clauses, name, before=index)
        if found is None:
            return current
        index, current = found
    return current


def _clause_index(clauses: list[a.AstNode], ret: a.Return) -> int:
    for i, clause in enumerate(clauses):
        if clause is ret:
            return i
    return len(clauses)


def _nearest_definition(
    clauses: list[a.AstNode],
    name: str,
    *,
    before: int,
) -> tuple[int, a.AstNode] | None:
    """Nearest ``WITH`` alias defining ``name`` strictly before index ``before``."""
    for i in range(min(before, len(clauses)) - 1, -1, -1):
        clause = clauses[i]
        if not isinstance(clause, a.With):
            continue
        for item in clause.expressions or []:
            if (
                isinstance(item, a.Alias)
                and isinstance(item.alias, a.Identifier)
                and item.alias.this == name
                and isinstance(item.this, a.AstNode)
            ):
                return i, item.this
    return None


def _find_return(node: a.AstNode) -> a.Return | None:
    if isinstance(node, a.Return):
        return node
    if isinstance(node, a.Query):
        for c in reversed(node.clauses):
            if isinstance(c, a.Return):
                return c
    if isinstance(node, a.Union):
        return _find_return(node.this)
    for child in node.walk():
        if isinstance(child, a.Return):
            return child
    return None


def _named_projections(ret: a.Return) -> dict[str, a.AstNode]:
    out: dict[str, a.AstNode] = {}
    for i, expr in enumerate(ret.expressions or []):
        if isinstance(expr, a.Alias) and isinstance(expr.alias, a.Identifier):
            out[expr.alias.this] = expr.this
        elif isinstance(expr, a.Identifier):
            out[expr.this] = expr
        elif isinstance(expr, a.Property) and isinstance(expr.this, a.Identifier):
            out[expr.name] = expr
        else:
            out[f"col_{i}"] = expr
    return out


def _to_node(
    name: str,
    expr: a.AstNode,
    source: a.AstNode,
    on_node: t.Callable[[Node], None] | None = None,
) -> Node:
    node = Node(name=name, expression=expr, source=source)
    for child in expr.find_all(a.Property, a.Identifier, a.Parameter, a.Literal):
        if child is expr:
            continue
        leaf = Node(
            name=getattr(child, "name", None)
            or getattr(child, "this", None)
            or type(child).__name__,
            expression=child,
            source=child,
        )
        if isinstance(leaf.name, a.AstNode):
            leaf.name = str(leaf.name)
        leaf.name = str(leaf.name)
        node.downstream.append(leaf)
        if on_node:
            on_node(leaf)
    if not node.downstream:
        leaf = Node(name=name, expression=expr, source=expr)
        node.downstream.append(leaf)
    if on_node:
        on_node(node)
    return node
