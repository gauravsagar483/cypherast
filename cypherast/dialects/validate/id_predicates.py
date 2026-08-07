"""Validate: id()/elementId() in string predicates."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _id_in_string_predicates(tree: a.AstNode) -> list[ConstraintIssue]:
    """Bare id()/elementId() compared as a string (CONTAINS / STARTS/ENDS / = / <>)."""

    def _is_id_call(n: a.AstNode | None) -> bool:
        return (
            isinstance(n, a.FunctionCall)
            and str(n.name).lower() in {"id", "elementid"}
        )

    def _is_string_lit(n: a.AstNode | None) -> bool:
        return isinstance(n, a.String) or (
            isinstance(n, a.Literal) and isinstance(getattr(n, "this", None), str)
        )

    for n in tree.find_all(a.Contains, a.StartsWith, a.EndsWith):
        left = getattr(n, "this", None)
        if _is_id_call(left):
            return [
                ConstraintIssue(
                    "CG1401",
                    "id()/elementId() is not a string; wrap with toString(...) for text predicates",
                    hint="WHERE toString(id(m)) CONTAINS '…' or match a schema string property",
                )
            ]
    for n in tree.find_all(a.EQ, a.NEQ):
        assert isinstance(n, (a.EQ, a.NEQ))
        if _is_id_call(n.this) and _is_string_lit(n.expression):
            return [
                ConstraintIssue(
                    "CG1401",
                    "id()/elementId() cannot equal a string key; use toString(id(n)) or a property",
                    hint="WHERE toString(id(n)) = '…' or n.key = '…'",
                )
            ]
        if _is_string_lit(n.this) and _is_id_call(n.expression):
            return [
                ConstraintIssue(
                    "CG1401",
                    "id()/elementId() cannot equal a string key; use toString(id(n)) or a property",
                    hint="WHERE toString(id(n)) = '…' or n.key = '…'",
                )
            ]
    return []
