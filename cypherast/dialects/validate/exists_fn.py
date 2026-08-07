"""Validate: exists() function calls."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _exists_function_calls(tree: a.AstNode) -> list[ConstraintIssue]:
    for n in tree.find_all(a.FunctionCall):
        assert isinstance(n, a.FunctionCall)
        if str(n.name).lower() == "exists":
            return [
                ConstraintIssue(
                    "CG1401",
                    "exists() is not supported by this dialect",
                    hint="Use a bare pattern predicate: WHERE NOT (a)-[:R]->(b)",
                )
            ]
    # EXISTS (path) as PatternPredicate(not_=False) — renderer handles; flag if Query form
    return []
