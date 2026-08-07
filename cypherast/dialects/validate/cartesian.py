"""Validate: Cartesian multi-path / consecutive MATCH."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _cartesian_matches(tree: a.AstNode) -> list[ConstraintIssue]:
    """Reject true Cartesians: disjoint multi-path MATCH or consecutive MATCH.

    Connected multi-path (shared variables) and consecutive MATCH that reuse
    prior bindings are allowed.
    """

    def _path_vars(path: a.PathPattern) -> set[str]:
        out: set[str] = set()
        for n in path.walk():
            if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
                n.variable, a.Identifier
            ):
                out.add(n.variable.this)
        return out

    def _pattern_vars(pattern: a.AstNode | None) -> set[str]:
        out: set[str] = set()
        if not isinstance(pattern, a.Pattern):
            return out
        for path in pattern.paths or []:
            if isinstance(path, a.PathPattern):
                out |= _path_vars(path)
        return out

    issues: list[ConstraintIssue] = []

    # 1) Multi-path in one MATCH — only when no shared vars across paths
    for n in tree.find_all(a.Match):
        assert isinstance(n, a.Match)
        if not isinstance(n.pattern, a.Pattern):
            continue
        paths = [p for p in (n.pattern.paths or []) if isinstance(p, a.PathPattern)]
        if len(paths) <= 1:
            continue
        shared: set[str] | None = None
        disjoint = False
        acc: set[str] = set()
        for path in paths:
            pv = _path_vars(path)
            if shared is None:
                shared = set(pv)
                acc = set(pv)
                continue
            if not (pv & acc):
                disjoint = True
                break
            acc |= pv
        if disjoint:
            issues.append(
                ConstraintIssue(
                    "CG1401",
                    "Multiple paths in one MATCH are rejected (Cartesian risk)",
                    hint="Connect paths with shared variables or split carefully",
                )
            )
            return issues

    # 2) Adjacent required MATCH (no WITH/UNWIND between) with no shared vars
    root = tree.this if isinstance(tree, a.Cypher) else tree
    queries = [root] if isinstance(root, a.Query) else list(tree.find_all(a.Query))
    for q in queries:
        assert isinstance(q, a.Query)
        prev_vars: set[str] | None = None
        for clause in q.clauses or []:
            if isinstance(clause, a.Match) and not clause.optional:
                here = _pattern_vars(clause.pattern)
                if (
                    prev_vars is not None
                    and here
                    and not (here & prev_vars)
                ):
                    issues.append(
                        ConstraintIssue(
                            "CG1401",
                            "Consecutive MATCH clauses with no shared variables "
                            "are rejected (Cartesian risk)",
                            hint="Share a variable between MATCH clauses or combine patterns",
                        )
                    )
                    return issues
                prev_vars = here if prev_vars is None else (prev_vars | here)
            elif isinstance(
                clause,
                (a.With, a.Unwind, a.Create, a.Merge, a.Set, a.Delete, a.Remove),
            ):
                # Projection / write breaks adjacency for Cartesian detection
                prev_vars = None
    return issues
