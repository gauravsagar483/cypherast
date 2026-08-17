"""Reject expression, pattern, and clause shapes absent from a read surface."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _map_projections(tree: a.AstNode) -> list[ConstraintIssue]:
    if not tree.find(a.MapProjection):
        return []
    return [
        ConstraintIssue(
            "CG1401",
            "Map projections are not supported by this dialect",
            hint="Return explicit properties with AS aliases",
        )
    ]


def _exists_subqueries(tree: a.AstNode) -> list[ConstraintIssue]:
    for pred in tree.find_all(a.PatternPredicate):
        assert isinstance(pred, a.PatternPredicate)
        if isinstance(pred.pattern, (a.Query, a.Union, a.Cypher)):
            return [
                ConstraintIssue(
                    "CG1401",
                    "EXISTS { … } subqueries are not supported by this dialect",
                    hint="Use a pattern predicate in WHERE or a CALL subquery",
                )
            ]
    return []


def _count_subqueries(tree: a.AstNode) -> list[ConstraintIssue]:
    if not tree.find(a.CountSubquery):
        return []
    return [
        ConstraintIssue(
            "CG1401",
            "COUNT { … } subqueries are not supported by this dialect",
            hint="Use MATCH followed by count(...)",
        )
    ]


def _multi_label_nodes(tree: a.AstNode) -> list[ConstraintIssue]:
    for node in tree.find_all(a.NodePattern):
        assert isinstance(node, a.NodePattern)
        labels = node.labels
        if not isinstance(labels, a.LabelExpression):
            continue
        if len(labels.labels or []) > 1 or "|" in str(labels.expression or ""):
            return [
                ConstraintIssue(
                    "CG1401",
                    "Multiple labels on one node pattern are not supported by this dialect",
                    hint="Match one label and filter using labels(n) if the engine supports it",
                )
            ]
    return []


_WRITE_NODES: tuple[type[a.AstNode], ...] = (
    a.Create,
    a.Merge,
    a.Set,
    a.Delete,
    a.Remove,
    a.Foreach,
    a.LoadCsv,
    a.AdminStatement,
)


def _write_clauses(tree: a.AstNode) -> list[ConstraintIssue]:
    for typ in _WRITE_NODES:
        if tree.find(typ):
            return [
                ConstraintIssue(
                    "CG1401",
                    f"{typ.__name__} is not supported by this read-only dialect",
                    hint="Run read clauses only",
                )
            ]
    return []


def _parameters(tree: a.AstNode) -> list[ConstraintIssue]:
    if not tree.find(a.Parameter):
        return []
    return [
        ConstraintIssue(
            "CG1401",
            "Parameters are not supported reliably by this dialect",
            hint="Inline a safely encoded literal before sending the query",
        )
    ]
