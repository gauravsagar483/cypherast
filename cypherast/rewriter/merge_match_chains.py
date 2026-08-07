"""Merge consecutive MATCH clauses that share variables into chained paths when safe."""

from __future__ import annotations

from cypherast import ast as a


def merge_match_chains(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    """Rewrite Query clauses: MATCH ... MATCH ... (no WHERE between) → single MATCH when
    the second pattern continues from a variable bound by the first.

    Conservative: only merges when second MATCH has no WHERE/OPTIONAL and is a simple
    continuation (shares at least one var). Stitches into one path when the second
    path starts with a shared node; otherwise leaves consecutive MATCH alone.
    """
    _ = schema

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
                chained = _stitch_patterns(cur.pattern, nxt.pattern)
                if chained is not None:
                    new_clauses.append(
                        a.Match(pattern=chained, optional=None, where=None)
                    )
                    i += 2
                    continue
            new_clauses.append(cur)
            i += 1
        node.clauses = new_clauses
        return node

    return tree.transform(_fix, copy=False)


def _shares_var(p1: a.Pattern, p2: a.Pattern) -> bool:
    return bool(_pattern_vars(p1) & _pattern_vars(p2))


def _pattern_vars(p: a.Pattern) -> set[str]:
    out: set[str] = set()
    for n in p.walk():
        if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
            n.variable, a.Identifier
        ):
            out.add(n.variable.this)
    return out


def _node_var(n: a.AstNode | None) -> str | None:
    if isinstance(n, a.NodePattern) and isinstance(n.variable, a.Identifier):
        return str(n.variable.this)
    return None


def _stitch_patterns(p1: a.Pattern, p2: a.Pattern) -> a.Pattern | None:
    """Try to concatenate paths at a shared endpoint node into one path."""
    paths1 = [p for p in (p1.paths or []) if isinstance(p, a.PathPattern)]
    paths2 = [p for p in (p2.paths or []) if isinstance(p, a.PathPattern)]
    if len(paths1) != 1 or len(paths2) != 1:
        return None
    left = list(paths1[0].elements or [])
    right = list(paths2[0].elements or [])
    if not left or not right:
        return None
    # Second path must start with a node whose var appears in the first path.
    start_var = _node_var(right[0])
    if start_var is None:
        return None
    # Prefer stitch when shared node is the last node of the first path.
    last_var = _node_var(left[-1])
    if last_var == start_var:
        # Keep left's node (may carry labels); drop right's duplicate start node.
        return a.Pattern(
            paths=[a.PathPattern(elements=left + right[1:], variable=paths1[0].variable)]
        )
    # Or first path is a lone node equal to right's start.
    if len(left) == 1 and last_var == start_var:
        return a.Pattern(
            paths=[a.PathPattern(elements=left + right[1:], variable=paths1[0].variable)]
        )
    return None
