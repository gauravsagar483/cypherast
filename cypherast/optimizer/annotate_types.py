"""Infer types from GraphSchema + function signatures + pattern bindings."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.schema import GraphSchema, lookup_function


def _collect_pattern_bindings(pattern: a.Pattern) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for path in pattern.paths:
        if path.variable:
            bindings[path.variable.this] = "path"
        for elem in path.elements:
            if isinstance(elem, a.ShortestPath) and isinstance(elem.this, a.PathPattern):
                inner = elem.this
                if inner.variable:
                    bindings[inner.variable.this] = "path"
                elems = inner.elements
            else:
                elems = [elem]
            for e in elems:
                if isinstance(e, a.NodePattern) and e.variable:
                    bindings[e.variable.this] = "node"
                elif isinstance(e, a.RelationshipPattern) and e.variable and not e.variable_length:
                    bindings[e.variable.this] = "relationship"
    return bindings


def _clause_bindings(tree: a.AstNode) -> dict[str, str]:
    bindings: dict[str, str] = {}
    query = tree.this if isinstance(tree, a.Cypher) else tree
    if isinstance(query, a.Union):
        for side in (query.this, query.expression):
            bindings.update(_clause_bindings(side))
        return bindings
    if not isinstance(query, a.Query):
        return bindings
    for clause in query.clauses:
        if isinstance(clause, a.Match) and clause.pattern:
            bindings.update(_collect_pattern_bindings(clause.pattern))
        elif isinstance(clause, a.With):
            for expr in clause.expressions or []:
                if isinstance(expr, a.Alias) and isinstance(expr.alias, a.Identifier):
                    bindings[expr.alias.this] = bindings.get(
                        expr.this.this if isinstance(expr.this, a.Identifier) else "",
                        "any",
                    )
    return bindings


def annotate_types(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    gs = schema if isinstance(schema, GraphSchema) else None
    pat_bindings = _clause_bindings(tree)

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, a.Integer):
            node.type = "integer"
        elif isinstance(node, a.Float):
            node.type = "float"
        elif isinstance(node, a.String):
            node.type = "string"
        elif isinstance(node, a.Boolean):
            node.type = "boolean"
        elif isinstance(node, a.Null):
            node.type = "null"
        elif isinstance(node, a.List):
            node.type = "list"
        elif isinstance(node, a.Map):
            node.type = "map"
        elif isinstance(node, a.Identifier) and node.this in pat_bindings:
            node.type = pat_bindings[node.this]
        elif isinstance(node, a.FunctionCall):
            sig = lookup_function(node.name)
            if sig:
                node.type = sig[1]
        elif isinstance(node, a.Property) and gs and isinstance(node.this, a.Identifier):
            for ld in gs.labels.values():
                if node.name in ld.properties:
                    node.type = ld.properties[node.name].type
                    break
        elif isinstance(node, a.Add):
            lt = getattr(node.this, "type", None)
            rt = getattr(node.expression, "type", None)
            if lt == "string" or rt == "string":
                node.type = "string"
            elif lt in ("integer", "float") or rt in ("integer", "float"):
                node.type = "float" if "float" in (lt, rt) else "integer"
        return node

    return tree.transform(_fix, copy=False)
