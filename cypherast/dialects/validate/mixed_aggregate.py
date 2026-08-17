"""Validate: aggregate mixed with a bare reference inside one projection item."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue
from cypherast.schema import AGGREGATE_FUNCTIONS


def _is_aggregate(node: a.AstNode) -> bool:
    return isinstance(node, a.FunctionCall) and str(node.name).lower() in AGGREGATE_FUNCTIONS


def _scan(node: a.AstNode) -> tuple[bool, bool]:
    """Return (contains aggregate, contains reference outside any aggregate)."""
    if _is_aggregate(node):
        return True, False
    has_agg = False
    has_ref = isinstance(node, a.Identifier)
    for child in node.args.values():
        items = child if isinstance(child, list) else [child]
        for item in items:
            if not isinstance(item, a.AstNode):
                continue
            child_agg, child_ref = _scan(item)
            has_agg = has_agg or child_agg
            has_ref = has_ref or child_ref
    return has_agg, has_ref


def _mixed_aggregate_projection(tree: a.AstNode) -> list[ConstraintIssue]:
    """Grouping keys must be standalone items: no ``key + count(*)`` in one expression."""
    for clause in tree.find_all(a.With, a.Return):
        for expr in getattr(clause, "expressions", None) or []:
            core = expr.this if isinstance(expr, a.Alias) else expr
            if not isinstance(core, a.AstNode):
                continue
            has_agg, has_ref = _scan(core)
            if has_agg and has_ref:
                alias = expr.alias if isinstance(expr, a.Alias) else None
                name = alias.this if isinstance(alias, a.Identifier) else alias
                where = f" (`{name}`)" if name else ""
                return [
                    ConstraintIssue(
                        "CG1401",
                        f"Aggregate mixed with a non-aggregate reference in one projection{where}",
                        hint=(
                            "Aggregate in an earlier WITH, then combine the aliases: "
                            "WITH count(DISTINCT x) AS c … RETURN toFloat(c) / total"
                        ),
                    )
                ]
    return []
