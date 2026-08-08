"""openCypher 9 excluded-clause validators."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue

_GQL_NODES: tuple[type[a.AstNode], ...] = (
    a.Next,
    a.Insert,
    a.Use,
    a.CreateGraphType,
    a.GraphTypeRef,
    a.SessionCommand,
    a.TransactionCommand,
    a.BindingTable,
    a.ValueTable,
)


def _reject_excluded_clauses(tree: a.AstNode) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    if tree.find(a.Foreach):
        issues.append(
            ConstraintIssue(
                "CG1501",
                "FOREACH is not in openCypher 9",
                hint="Rewrite with UNWIND or separate write queries",
            )
        )
    for merge in tree.find_all(a.Merge):
        assert isinstance(merge, a.Merge)
        for action in merge.actions or []:
            if isinstance(action, (a.OnCreate, a.OnMatch)):
                issues.append(
                    ConstraintIssue(
                        "CG1502",
                        "MERGE ON CREATE / ON MATCH actions are not in openCypher 9",
                        hint="Use separate MATCH + SET or CREATE clauses",
                    )
                )
                break
    return issues


def _reject_call_subquery(tree: a.AstNode) -> list[ConstraintIssue]:
    if tree.find(a.CallSubquery):
        return [
            ConstraintIssue(
                "CG1505",
                "CALL { … } subqueries are not in openCypher 9",
                hint="Use CALL procedure.name(…) YIELD … for procedures",
            )
        ]
    return []


def _reject_gql_nodes(tree: a.AstNode) -> list[ConstraintIssue]:
    for typ in _GQL_NODES:
        if tree.find(typ):
            return [
                ConstraintIssue(
                    "CG1506",
                    f"{typ.__name__} is not in openCypher 9",
                    hint="Use openCypher clauses only",
                )
            ]
    return []
