"""Validate: UNION branch column name alignment."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _return_column_names(ret: a.Return) -> list[str]:
    names: list[str] = []
    for i, expr in enumerate(ret.expressions or []):
        if isinstance(expr, a.Alias):
            if isinstance(expr.alias, a.Identifier):
                names.append(expr.alias.this)
            elif isinstance(expr.alias, str):
                names.append(expr.alias)
            else:
                names.append(f"col{i}")
        elif isinstance(expr, a.Identifier):
            names.append(expr.this)
        elif isinstance(expr, a.Property) and isinstance(expr.this, a.Identifier):
            names.append(f"{expr.this.this}.{expr.name}" if hasattr(expr, "name") else f"col{i}")
        else:
            names.append(f"col{i}")
    return names


def _union_leaf_branches(node: a.AstNode) -> list[a.AstNode]:
    if isinstance(node, a.Union):
        return _union_leaf_branches(node.this) + _union_leaf_branches(node.expression)
    return [node]


def _union_column_mismatch(tree: a.AstNode) -> list[ConstraintIssue]:
    root = tree.this if isinstance(tree, a.Cypher) else tree
    unions = [root] if isinstance(root, a.Union) else list(tree.find_all(a.Union))
    for u in unions:
        assert isinstance(u, a.Union)
        cols: list[list[str]] | None = None
        for br in _union_leaf_branches(u):
            q = br.this if isinstance(br, a.Cypher) else br
            if not isinstance(q, a.Query):
                continue
            rets = [c for c in (q.clauses or []) if isinstance(c, a.Return)]
            if not rets:
                continue
            names = _return_column_names(rets[-1])
            if cols is None:
                cols = [names]
            elif names != cols[0]:
                return [
                    ConstraintIssue(
                        "CG1401",
                        "UNION branches must return identical column names in the same order",
                        hint=f"Got {names} vs {cols[0]} — align AS aliases across branches",
                    )
                ]
    return []
