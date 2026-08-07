"""Rewrite: split multi-path MATCH into consecutive MATCH clauses."""

from __future__ import annotations

from cypherast import ast as a


def split_multi_path_match(tree: a.AstNode) -> a.AstNode:
    """``MATCH p1, p2`` → consecutive ``MATCH p1`` ``MATCH p2`` (shared vars OK)."""

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if not isinstance(node, a.Query):
            return node
        new_clauses: list[a.AstNode] = []
        for clause in node.clauses or []:
            if (
                isinstance(clause, a.Match)
                and isinstance(clause.pattern, a.Pattern)
                and len(clause.pattern.paths or []) > 1
            ):
                paths = list(clause.pattern.paths)
                # Keep WHERE on the last split fragment
                for i, path in enumerate(paths):
                    where = clause.where if i == len(paths) - 1 else None
                    new_clauses.append(
                        a.Match(
                            pattern=a.Pattern(paths=[path]),
                            optional=clause.optional,
                            where=where,
                        )
                    )
            else:
                new_clauses.append(clause)
        node.clauses = new_clauses
        return node

    return tree.transform(_fix, copy=False)

