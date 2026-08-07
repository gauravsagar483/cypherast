"""Qualify: auto-name anonymous pattern elements, resolve WITH scopes."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.scope import build_scope


def qualify(
    tree: a.AstNode,
    schema: object | None = None,
    *,
    require_labelled_nodes: bool = False,
) -> a.AstNode:
    """Name anonymous pattern elements.

    When ``require_labelled_nodes`` (e.g. PuppyGraph), do **not** invent variables
    for unlabelled anonymous nodes — leave ``()`` so dialect validate can report
    unlabelled MATCH endpoints instead of fake ``(_n_1)`` bindings.
    """
    _ = schema
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

    def _node_labels(node: a.NodePattern) -> list[str] | None:
        if isinstance(node.labels, a.LabelExpression):
            return list(node.labels.labels or [])
        return None

    def _fix(node: a.AstNode) -> a.AstNode | None:
        # Pattern predicates must not introduce new bindings.
        if _under_pattern_predicate(node):
            return node
        if isinstance(node, a.NodePattern) and node.variable is None:
            labels = _node_labels(node)
            if require_labelled_nodes and not labels:
                return node
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
