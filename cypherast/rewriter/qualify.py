"""Qualify: auto-name anonymous pattern elements, resolve WITH scopes."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.scope import build_scope


def qualify(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    counter = {"n": 0, "r": 0, "p": 0}

    def _name(prefix: str) -> str:
        counter[prefix] += 1
        return f"_{prefix}_{counter[prefix]}"

    def _under_pattern_predicate(node: a.AstNode) -> bool:
        parent = node.parent
        while parent is not None:
            if isinstance(parent, a.PatternPredicate):
                return True
            parent = parent.parent
        return False

    def _fix(node: a.AstNode) -> a.AstNode | None:
        # Pattern predicates must not introduce new bindings (openCypher / PuppyGraph).
        if _under_pattern_predicate(node):
            return node
        if isinstance(node, a.NodePattern) and node.variable is None:
            node.variable = a.Identifier(this=_name("n"))
        elif (
            isinstance(node, a.RelationshipPattern)
            and node.variable is None
            and (node.types or node.properties or node.variable_length)
        ):
            node.variable = a.Identifier(this=_name("r"))
        return node

    result = tree.transform(_fix, copy=False)
    build_scope(result)
    return result
