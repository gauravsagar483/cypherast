"""Merge consecutive MATCH clauses that share variables into chained paths when safe."""

from __future__ import annotations

from cypherglot import ast as a


def merge_match_chains(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    """Rewrite Query clauses: MATCH ... MATCH ... (no WHERE between) → single MATCH when
    the second pattern starts from a variable bound by the first.

    Conservative: only merges when second MATCH has no WHERE/OPTIONAL and is a simple
    continuation (shares at least one var).
    """

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if not isinstance(node, a.Query):
            return node
        new_clauses: list[a.AstNode] = []
        i = 0
        clauses = list(node.clauses or [])
        while i < len(clauses):
            cur = clauses[i]
            if (
                isinstance(cur, a.Match)
                and not cur.optional
                and cur.where is None
                and i + 1 < len(clauses)
                and isinstance(clauses[i + 1], a.Match)
                and not clauses[i + 1].optional
                and clauses[i + 1].where is None
                and _shares_var(cur.pattern, clauses[i + 1].pattern)
            ):
                nxt = clauses[i + 1]
                merged = a.Match(
                    pattern=a.Pattern(
                        paths=list(cur.pattern.paths) + list(nxt.pattern.paths)
                    ),
                    optional=None,
                    where=None,
                )
                new_clauses.append(merged)
                i += 2
                continue
            new_clauses.append(cur)
            i += 1
        node.clauses = new_clauses
        return node

    return tree.transform(_fix, copy=False)


def _shares_var(p1: a.Pattern, p2: a.Pattern) -> bool:
    def vars_of(p: a.Pattern) -> set[str]:
        out: set[str] = set()
        for n in p.walk():
            if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
                n.variable, a.Identifier
            ):
                out.add(n.variable.this)
        return out

    return bool(vars_of(p1) & vars_of(p2))
