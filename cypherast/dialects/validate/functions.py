"""Validate built-in function names, exclusions, and arity."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue
from cypherast.schema import (
    AGGREGATE_FUNCTIONS,
    FUNCTION_OPTIONAL_ARGS,
    FUNCTION_VARIADIC_MIN,
    OC9_EXCLUDED_FUNCTIONS,
    lookup_function,
)

# OC9 aggregate names accepted with DISTINCT / * — arity checked loosely
_AGGREGATES = AGGREGATE_FUNCTIONS


def _function_signature_issues(tree: a.AstNode) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    for node in tree.find_all(a.FunctionCall):
        assert isinstance(node, a.FunctionCall)
        raw = str(node.name)
        lower = raw.lower()
        if lower in OC9_EXCLUDED_FUNCTIONS:
            issues.append(
                ConstraintIssue(
                    "CG1507",
                    f"Function {raw!r} is excluded from openCypher 9",
                    hint="See standardisation-scope.adoc for included functions",
                )
            )
            continue
        sig = lookup_function(raw)
        if sig is None:
            issues.append(
                ConstraintIssue(
                    "CG1508",
                    f"Unknown function {raw!r}",
                    hint="Check spelling against openCypher 9 built-ins",
                )
            )
            continue
        nargs = len(node.expressions)
        if lower in FUNCTION_VARIADIC_MIN:
            if nargs < FUNCTION_VARIADIC_MIN[lower]:
                issues.append(
                    ConstraintIssue(
                        "CG1509",
                        f"Function {raw!r} expects at least "
                        f"{FUNCTION_VARIADIC_MIN[lower]} argument(s), got {nargs}",
                    )
                )
            continue
        if lower in _AGGREGATES:
            continue
        expected = len(sig[0])
        optional = FUNCTION_OPTIONAL_ARGS.get(lower, 0)
        min_args = expected - optional
        max_args = expected
        if nargs < min_args or nargs > max_args:
            issues.append(
                ConstraintIssue(
                    "CG1509",
                    f"Function {raw!r} expects {min_args}"
                    + (f"–{max_args}" if max_args != min_args else "")
                    + f" argument(s), got {nargs}",
                )
            )
    return issues
