"""Validate built-in function names, exclusions, and arity."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
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


def _function_signature_issues(
    tree: a.AstNode, caps: DialectCapabilities
) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    arity_overrides = {
        name.lower(): (min_args, max_args)
        for name, min_args, max_args in caps.function_arity_overrides
    }
    nodes = tree.find_all(a.FunctionCall, a.Coalesce, a.Quantifier, a.ListLambda)
    for node in nodes:
        if isinstance(node, a.FunctionCall):
            raw = str(node.name)
            nargs = len(node.expressions)
        elif isinstance(node, a.Coalesce):
            raw = "coalesce"
            nargs = len(node.expressions)
        elif isinstance(node, a.Quantifier):
            raw = str(node.name)
            nargs = 1
        else:
            assert isinstance(node, a.ListLambda)
            raw = str(node.name)
            nargs = 1
        lower = raw.lower()
        if lower in caps.unsupported_functions:
            issues.append(
                ConstraintIssue(
                    "CG1507",
                    f"Function {raw!r} is not supported by this dialect",
                )
            )
            continue
        if lower in OC9_EXCLUDED_FUNCTIONS and lower not in caps.allowed_functions:
            issues.append(
                ConstraintIssue(
                    "CG1507",
                    f"Function {raw!r} is excluded from openCypher 9",
                    hint="See standardisation-scope.adoc for included functions",
                )
            )
            continue
        if isinstance(node, (a.Quantifier, a.ListLambda)):
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
        if lower in arity_overrides:
            min_args, max_args = arity_overrides[lower]
            if nargs < min_args or nargs > max_args:
                issues.append(
                    ConstraintIssue(
                        "CG1509",
                        f"Function {raw!r} expects {min_args}"
                        + (f"–{max_args}" if max_args != min_args else "")
                        + f" argument(s), got {nargs}",
                    )
                )
            continue
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
