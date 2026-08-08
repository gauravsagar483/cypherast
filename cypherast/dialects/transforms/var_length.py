"""Rewrite: clamp variable-length hop bounds."""

from __future__ import annotations

from cypherast import ast as a


def bound_variable_length(tree: a.AstNode, *, max_hops: int, allow_unbounded: bool) -> a.AstNode:
    def _fix(node: a.AstNode) -> a.AstNode | None:
        if not isinstance(node, a.RelationshipPattern) or not node.variable_length:
            return node
        hi = node.max_hops
        if hi is None and not allow_unbounded or hi is not None and hi > max_hops:
            node.max_hops = max_hops
        if node.min_hops is None:
            node.min_hops = 0
        return node

    return tree.transform(_fix, copy=False)
