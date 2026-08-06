"""Canonicalize patterns per openCypher Style Guide (outgoing L->R preference)."""

from __future__ import annotations

from cypherglot import ast as a


def canonicalize_patterns(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    def _fix(node: a.AstNode) -> a.AstNode | None:
        if not isinstance(node, a.PathPattern):
            return node
        # Prefer outgoing: if single rel is INCOMING, flip the path
        elems = node.elements
        if len(elems) == 3 and isinstance(elems[1], a.RelationshipPattern):
            rel = elems[1]
            if rel.direction is a.Direction.INCOMING:
                rel.direction = a.Direction.OUTGOING
                node.elements = [elems[2], rel, elems[0]]
        return node

    return tree.transform(_fix, copy=False)
