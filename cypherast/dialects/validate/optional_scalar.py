"""Validate: unguarded OPTIONAL scalar use (FET-45)."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.transforms.guard_optional_scalar import (
    _call_under_null_case_guard,
    _optional_pattern_vars,
    _where_is_not_null_guard,
)
from cypherast.dialects.validate.issues import ConstraintIssue


def _unguarded_optional_scalar_use(
    tree: a.AstNode,
    *,
    risky_functions: frozenset[str],
) -> list[ConstraintIssue]:
    """FET-45: OPTIONAL-bound vars in id()/split/… without a null guard."""
    if not risky_functions:
        return []
    optional_vars = _optional_pattern_vars(tree)
    if not optional_vars:
        return []

    for call in tree.find_all(a.FunctionCall):
        assert isinstance(call, a.FunctionCall)
        if str(call.name).lower() not in risky_functions:
            continue
        for n in call.walk():
            if not (isinstance(n, a.Identifier) and n.this in optional_vars):
                continue
            var = n.this
            if _call_under_null_case_guard(call, var):
                continue
            if _where_is_not_null_guard(tree, var):
                continue
            return [
                ConstraintIssue(
                    "CG1401",
                    f"OPTIONAL-bound `{var}` used in {call.name}() without null guard",
                    hint=(
                        f"Add CASE WHEN {var} IS NULL THEN NULL ELSE … END "
                        f"or WHERE {var} IS NOT NULL"
                    ),
                )
            ]
    return []
