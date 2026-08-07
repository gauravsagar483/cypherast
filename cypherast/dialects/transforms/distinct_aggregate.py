"""Rewrite: DISTINCT beside aggregates + collect(DISTINCT) caps."""

from __future__ import annotations

from cypherast import ast as a


def drop_distinct_beside_aggregate(tree: a.AstNode) -> a.AstNode:
    """``WITH/RETURN DISTINCT …, count(…)`` → drop DISTINCT (grouping already implied)."""

    def _has_agg(expressions: list[a.AstNode] | None) -> bool:
        for expr in expressions or []:
            node = expr.this if isinstance(expr, a.Alias) else expr
            if isinstance(node, a.FunctionCall) and str(node.name).lower() in {
                "count",
                "sum",
                "avg",
                "min",
                "max",
                "collect",
            }:
                return True
        return False

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, (a.With, a.Return)) and node.distinct and _has_agg(
            node.expressions
        ):
            node.distinct = None
        return node

    return tree.transform(_fix, copy=False)


def cap_collect_distinct(tree: a.AstNode, *, max_n: int) -> a.AstNode:
    """If > max collect(DISTINCT) in one clause, convert extras to count(DISTINCT).

    Prefer leaving a single collect(DISTINCT) and rewriting additional ones to count.
    """

    def _rewrite_exprs(expressions: list[a.AstNode]) -> list[a.AstNode]:
        seen = 0
        out: list[a.AstNode] = []
        for expr in expressions:
            core = expr.this if isinstance(expr, a.Alias) else expr
            if (
                isinstance(core, a.FunctionCall)
                and str(core.name).lower() == "collect"
                and core.distinct
            ):
                seen += 1
                if seen > max_n:
                    replacement = a.FunctionCall(
                        name="count", expressions=list(core.expressions), distinct=True
                    )
                    if isinstance(expr, a.Alias):
                        out.append(a.Alias(this=replacement, alias=expr.alias))
                    else:
                        out.append(replacement)
                    continue
            out.append(expr)
        return out

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, (a.With, a.Return)) and node.expressions:
            node.expressions = _rewrite_exprs(list(node.expressions))
        return node

    return tree.transform(_fix, copy=False)
