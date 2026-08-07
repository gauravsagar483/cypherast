"""Validate: NULLS FIRST/LAST order modifiers."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _nulls_order_modifiers(tree: a.AstNode) -> list[ConstraintIssue]:
    for n in tree.find_all(a.Ordered):
        assert isinstance(n, a.Ordered)
        if n.nulls:
            return [
                ConstraintIssue(
                    "CG1401",
                    "ORDER BY NULLS FIRST/LAST is not supported by this dialect",
                    hint="Omit NULLS modifiers (optimize strips them when rewriting)",
                )
            ]
    return []
