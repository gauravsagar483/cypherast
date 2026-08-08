"""Validate: DISTINCT+agg, collect(DISTINCT) caps, TE-14."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _collect_distinct_with_other_aggregates(tree: a.AstNode) -> list[ConstraintIssue]:
    """TE-14: collect(DISTINCT) cannot sit beside other aggregates in one clause."""
    aggs = {"count", "sum", "avg", "min", "max", "collect"}
    for n in tree.find_all(a.With, a.Return):
        exprs = getattr(n, "expressions", None) or []
        cores: list[a.AstNode] = []
        for expr in exprs:
            cores.append(expr.this if isinstance(expr, a.Alias) else expr)
        has_collect_d = any(
            isinstance(c, a.FunctionCall) and str(c.name).lower() == "collect" and c.distinct
            for c in cores
        )
        if not has_collect_d:
            continue
        other = any(
            isinstance(c, a.FunctionCall)
            and str(c.name).lower() in aggs
            and not (str(c.name).lower() == "collect" and c.distinct)
            for c in cores
        )
        # TE-14: collect(DISTINCT) + any other aggregate (multi collect_d → APT-18)
        if other:
            return [
                ConstraintIssue(
                    "CG1401",
                    "collect(DISTINCT …) cannot combine with other aggregates in the same clause",
                    hint="Use only collect(DISTINCT) alone, or only count(DISTINCT …) tallies",
                )
            ]
    return []


def _distinct_with_aggregate(tree: a.AstNode) -> list[ConstraintIssue]:
    for n in tree.find_all(a.With, a.Return):
        if not getattr(n, "distinct", None):
            continue
        for expr in getattr(n, "expressions", None) or []:
            core = expr.this if isinstance(expr, a.Alias) else expr
            if isinstance(core, a.FunctionCall) and str(core.name).lower() in {
                "count",
                "sum",
                "avg",
                "min",
                "max",
                "collect",
            }:
                return [
                    ConstraintIssue(
                        "CG1401",
                        "DISTINCT cannot combine with aggregates in the same clause",
                        hint="WITH DISTINCT keys first (no agg), then aggregate in the next WITH",
                    )
                ]
    return []


def _too_many_collect_distinct(tree: a.AstNode, max_n: int) -> list[ConstraintIssue]:
    for n in tree.find_all(a.With, a.Return):
        count = 0
        for expr in getattr(n, "expressions", None) or []:
            core = expr.this if isinstance(expr, a.Alias) else expr
            if (
                isinstance(core, a.FunctionCall)
                and str(core.name).lower() == "collect"
                and core.distinct
            ):
                count += 1
        if count > max_n:
            return [
                ConstraintIssue(
                    "CG1401",
                    f"At most {max_n} collect(DISTINCT …) per WITH/RETURN",
                    hint="Use count(DISTINCT …) for extra tallies, or one string-collect per clause",
                )
            ]
    return []
