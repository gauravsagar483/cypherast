"""Infer types from GraphSchema + function signatures."""

from __future__ import annotations

from cypherglot import ast as a
from cypherglot.schema import GraphSchema, lookup_function


def annotate_types(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    gs = schema if isinstance(schema, GraphSchema) else None

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
        elif isinstance(node, a.FunctionCall):
            sig = lookup_function(node.name)
            if sig:
                node.type = sig[1]
        elif isinstance(node, a.Property) and gs and isinstance(node.this, a.Identifier):
            # best-effort: scan all labels for property
            for ld in gs.labels.values():
                if node.name in ld.properties:
                    node.type = ld.properties[node.name].type
                    break
        return node

    return tree.transform(_fix, copy=False)
