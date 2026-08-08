"""openCypher 9 pattern validators."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _reject_undirected_patterns(tree: a.AstNode) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    for rel in tree.find_all(a.RelationshipPattern):
        assert isinstance(rel, a.RelationshipPattern)
        if rel.direction is a.Direction.BOTH:
            issues.append(
                ConstraintIssue(
                    "CG1503",
                    "Undirected relationship patterns are not in openCypher 9",
                    hint="Use directed arrows: -[:TYPE]-> or <-[:TYPE]-",
                )
            )
    return issues


def _reject_var_length_binding(tree: a.AstNode) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    for rel in tree.find_all(a.RelationshipPattern):
        assert isinstance(rel, a.RelationshipPattern)
        if rel.variable and rel.variable_length:
            issues.append(
                ConstraintIssue(
                    "CG1504",
                    "Binding a variable to a variable-length relationship is not in openCypher 9",
                    hint="Use an anonymous variable-length pattern or bind a path variable",
                )
            )
    return issues


def _reject_quantified_path(tree: a.AstNode) -> list[ConstraintIssue]:
    if tree.find(a.QuantifiedPath):
        return [
            ConstraintIssue(
                "CG1510",
                "Quantified path patterns are not in openCypher 9",
                hint="Expand to fixed-length or variable-length patterns",
            )
        ]
    return []


def _reject_using_hints(tree: a.AstNode) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    for match in tree.find_all(a.Match):
        assert isinstance(match, a.Match)
        if match.hints:
            issues.append(
                ConstraintIssue(
                    "CG1511",
                    "USING INDEX / SCAN / JOIN hints are not in openCypher 9",
                    hint="Remove planner hints from MATCH",
                )
            )
    return issues
