"""Validate: pattern predicates must not introduce new binders."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _pattern_predicate_bindings(tree: a.AstNode) -> list[ConstraintIssue]:
    """Reject new binders inside WHERE path patterns (Neo4j path-pattern rule).

    Outer-scope reuse is OK: ``WHERE (n)-[:R]->(:Person)`` when ``n`` already bound.
    New names like ``(m:Person)`` inside the predicate are not allowed.
    """

    def _pattern_vars(pattern: a.AstNode | None) -> set[str]:
        out: set[str] = set()
        if pattern is None:
            return out
        for n in pattern.walk():
            if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
                n.variable, a.Identifier
            ):
                out.add(n.variable.this)
        return out

    def _check_query(q: a.Query) -> list[ConstraintIssue]:
        scope: set[str] = set()
        for clause in q.clauses or []:
            if isinstance(clause, (a.Match, a.Create, a.Merge)):
                # WHERE pattern preds: MATCH pattern vars are in scope; new binders are not.
                prior = set(scope)
                added = _pattern_vars(clause.pattern)
                where_scope = prior | added
                where = getattr(clause, "where", None)
                for pred in where.find_all(a.PatternPredicate) if where else []:
                    assert isinstance(pred, a.PatternPredicate)
                    for n in pred.walk():
                        if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
                            n.variable, a.Identifier
                        ):
                            name = n.variable.this
                            if name not in where_scope:
                                return [
                                    ConstraintIssue(
                                        "CG1401",
                                        "Pattern predicates must not introduce new variables",
                                        hint=(
                                            "Keep anonymous (:Label) / -[:TYPE]- inside "
                                            "WHERE patterns; bind names in MATCH first"
                                        ),
                                    )
                                ]
                scope |= added
            elif isinstance(clause, a.With):
                nxt: set[str] = set()
                for expr in clause.expressions or []:
                    if isinstance(expr, a.Alias):
                        if isinstance(expr.alias, a.Identifier):
                            nxt.add(expr.alias.this)
                        elif isinstance(expr.alias, str):
                            nxt.add(expr.alias)
                    elif isinstance(expr, a.Identifier):
                        nxt.add(expr.this)
                scope = nxt
            elif isinstance(clause, a.Unwind):
                if isinstance(clause.alias, a.Identifier):
                    scope.add(clause.alias.this)
                elif isinstance(clause.alias, str):
                    scope.add(clause.alias)
        return []

    root = tree.this if isinstance(tree, a.Cypher) else tree
    if isinstance(root, a.Query):
        return _check_query(root)
    if isinstance(root, a.Union):
        for q in root.find_all(a.Query):
            assert isinstance(q, a.Query)
            issues = _check_query(q)
            if issues:
                return issues
    return []
