"""Rewrite: strip NULLS FIRST/LAST order modifiers."""

from __future__ import annotations

from cypherast import ast as a


def strip_nulls_order_modifiers(tree: a.AstNode) -> a.AstNode:
    """Drop ``NULLS FIRST/LAST`` when dialect forbids them."""

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, a.Ordered) and node.nulls:
            node.nulls = None
        return node

    return tree.transform(_fix, copy=False)
