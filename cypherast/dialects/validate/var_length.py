"""Validate: variable-length hop bounds."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _bad_var_length(
    tree: a.AstNode, *, max_hops: int, allow_unbounded: bool
) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    for n in tree.find_all(a.RelationshipPattern):
        assert isinstance(n, a.RelationshipPattern)
        if not n.variable_length:
            continue
        if n.max_hops is None and not allow_unbounded:
            issues.append(
                ConstraintIssue(
                    "CG1401",
                    "Unbounded variable-length paths are not allowed",
                    hint=f"Use a bounded form *0..{max_hops} (max {max_hops} hops)",
                )
            )
            break
        if n.max_hops is not None and int(n.max_hops) > max_hops:
            issues.append(
                ConstraintIssue(
                    "CG1401",
                    f"Variable-length path exceeds max hops ({max_hops})",
                    hint=f"Clamp to *lo..{max_hops}",
                )
            )
            break
    return issues
