"""Validate: undefined variables (CG1201)."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _undefined_variables(tree: a.AstNode) -> list[ConstraintIssue]:
    """Flag identifiers used outside scope (CG1201)."""

    def _issue(name: str, hint: str) -> list[ConstraintIssue]:
        return [
            ConstraintIssue(
                "CG1201",
                f"Variable `{name}` is not defined in this scope",
                hint=hint,
            )
        ]

    def _alias_name(expr: a.AstNode) -> str | None:
        if isinstance(expr, a.Alias):
            if isinstance(expr.alias, a.Identifier):
                return str(expr.alias.this)
            if isinstance(expr.alias, str):
                return expr.alias
        if isinstance(expr, a.Identifier):
            return str(expr.this)
        return None

    def _add_pattern_vars(pattern: a.AstNode | None, scope: set[str]) -> None:
        if pattern is None:
            return
        for n in pattern.walk():
            if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
                n.variable, a.Identifier
            ):
                scope.add(n.variable.this)
            if isinstance(n, a.PathPattern) and isinstance(n.variable, a.Identifier):
                scope.add(n.variable.this)

    def _pattern_pred_binders(node: a.AstNode | None) -> set[str]:
        """Variables declared inside PatternPredicate (not outer scope)."""
        out: set[str] = set()
        if node is None:
            return out
        for pred in node.find_all(a.PatternPredicate):
            for n in pred.walk():
                if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
                    n.variable, a.Identifier
                ):
                    out.add(n.variable.this)
        return out

    def _comprehension_binders(node: a.AstNode | None) -> set[str]:
        """Binders introduced by list / pattern comprehensions."""
        out: set[str] = set()
        if node is None:
            return out
        for comp in node.find_all(a.ListComprehension, a.PatternComprehension):
            if isinstance(comp, a.ListComprehension):
                if isinstance(comp.variable, a.Identifier):
                    out.add(comp.variable.this)
            elif isinstance(comp, a.PatternComprehension):
                if isinstance(comp.variable, a.Identifier):
                    out.add(comp.variable.this)
                if comp.pattern is not None:
                    for n in comp.pattern.walk():
                        if isinstance(
                            n, (a.NodePattern, a.RelationshipPattern)
                        ) and isinstance(n.variable, a.Identifier):
                            out.add(n.variable.this)
        return out

    def _local_binders(node: a.AstNode | None) -> set[str]:
        return _pattern_pred_binders(node) | _comprehension_binders(node)

    def _refs(node: a.AstNode | None, *, ignore: set[str] | None = None) -> set[str]:
        if node is None:
            return set()
        skip = ignore or set()
        out: set[str] = set()
        for n in node.walk():
            if isinstance(n, a.Identifier):
                parent = n.parent
                if isinstance(parent, a.FunctionCall) and parent.name == n.this:
                    continue
                if n.this in skip:
                    continue
                out.add(n.this)
        return out

    def _return_aliases(node: a.AstNode | None) -> set[str]:
        """Names exported by a subquery / branch RETURN (or UNION arms)."""
        if node is None:
            return set()
        if isinstance(node, a.Cypher):
            return _return_aliases(node.this)
        if isinstance(node, a.Union):
            return _return_aliases(node.this) | _return_aliases(node.expression)
        if isinstance(node, a.Query):
            for clause in reversed(node.clauses or []):
                if isinstance(clause, a.Return):
                    out: set[str] = set()
                    for expr in clause.expressions or []:
                        if isinstance(expr, a.Star):
                            continue
                        an = _alias_name(expr)
                        if an:
                            out.add(an)
                    return out
            return set()
        return set()

    def _check_query(
        q: a.Query,
        *,
        initial: set[str] | None = None,
        enclosing: set[str] | None = None,
    ) -> list[ConstraintIssue]:
        scope: set[str] = set(initial or ())
        for clause in q.clauses or []:
            if isinstance(clause, (a.Match, a.Create, a.Merge)):
                _add_pattern_vars(clause.pattern, scope)
                where = getattr(clause, "where", None)
                binders = _local_binders(where)
                for name in _refs(where, ignore=binders):
                    if name not in scope:
                        return _issue(
                            name, "Project it in WITH or reintroduce via MATCH"
                        )
            elif isinstance(clause, a.With):
                # Subquery leading WITH may import from enclosing outer scope.
                with_scope = scope | (enclosing or set())
                for expr in clause.expressions or []:
                    if isinstance(expr, a.Star):
                        continue
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    binders = _local_binders(core)
                    for name in _refs(core, ignore=binders):
                        if name not in with_scope:
                            return _issue(
                                name, "Project it in a prior WITH or MATCH"
                            )
                has_star = any(
                    isinstance(expr, a.Star) for expr in (clause.expressions or [])
                )
                nxt: set[str] = set(scope) if has_star else set()
                for expr in clause.expressions or []:
                    an = _alias_name(expr)
                    if an:
                        nxt.add(an)
                binders = _local_binders(clause.where)
                for name in _refs(clause.where, ignore=binders):
                    # WITH WHERE may only see projected aliases (not pre-WITH scope)
                    if name not in nxt:
                        return _issue(name, "WITH WHERE uses projected aliases")
                for sub in (clause.order, clause.skip, clause.limit):
                    for name in _refs(sub):
                        if name not in nxt:
                            return _issue(
                                name,
                                "WITH ORDER BY / SKIP / LIMIT use projected aliases",
                            )
                scope = nxt
                # After first WITH, imports are explicit — drop enclosing.
                enclosing = None
            elif isinstance(clause, a.Unwind):
                for name in _refs(clause.expression):
                    if name not in scope:
                        return _issue(name, "Project it before UNWIND")
                if isinstance(clause.alias, a.Identifier):
                    scope.add(clause.alias.this)
                elif isinstance(clause.alias, str):
                    scope.add(clause.alias)
            elif isinstance(clause, a.CallProcedure):
                for arg in clause.expressions or []:
                    for name in _refs(arg):
                        if name not in scope:
                            return _issue(name, "Bind procedure arguments before CALL")
                yielded: set[str] = set()
                if clause.yield_ is not None:
                    for expr in clause.yield_.expressions or []:
                        if isinstance(expr, a.Star):
                            # YIELD * — unknown field set; do not shrink scope
                            continue
                        an = _alias_name(expr)
                        if an:
                            yielded.add(an)
                where_scope = scope | yielded
                for name in _refs(clause.where):
                    if name not in where_scope:
                        return _issue(name, "YIELD the name before WHERE, or bind earlier")
                scope = scope | yielded
            elif isinstance(clause, a.CallSubquery):
                inner = clause.query
                # Classic CALL { }: empty inner scope; leading WITH imports from outer.
                # CALL (*) / CALL (vars) when variables is set (parser may add later).
                init: set[str] = set()
                vars_ = getattr(clause, "variables", None)
                if vars_ is not None:
                    if isinstance(vars_, a.Star):
                        init = set(scope)
                    elif isinstance(vars_, list):
                        for v in vars_:
                            if isinstance(v, a.Identifier) and v.this in scope:
                                init.add(v.this)
                            elif isinstance(v, str) and v in scope:
                                init.add(v)
                branches: list[a.Query] = []
                if isinstance(inner, a.Query):
                    branches = [inner]
                elif isinstance(inner, a.Union):
                    for qn in inner.find_all(a.Query):
                        assert isinstance(qn, a.Query)
                        branches.append(qn)
                elif isinstance(inner, a.Cypher) and isinstance(inner.this, a.Query):
                    branches = [inner.this]
                elif isinstance(inner, a.Cypher) and isinstance(inner.this, a.Union):
                    for qn in inner.this.find_all(a.Query):
                        assert isinstance(qn, a.Query)
                        branches.append(qn)
                for branch in branches:
                    issues = _check_query(
                        branch, initial=set(init), enclosing=set(scope)
                    )
                    if issues:
                        return issues
                scope = scope | _return_aliases(inner)
            elif isinstance(clause, a.Set):
                for item in clause.items or []:
                    for name in _refs(item):
                        if name not in scope:
                            return _issue(name, "Bind it before SET")
            elif isinstance(clause, a.Delete):
                for expr in clause.expressions or []:
                    for name in _refs(expr):
                        if name not in scope:
                            return _issue(name, "Bind it before DELETE")
            elif isinstance(clause, a.Remove):
                for item in clause.items or []:
                    for name in _refs(item):
                        if name not in scope:
                            return _issue(name, "Bind it before REMOVE")
            elif isinstance(clause, a.Return):
                ret_aliases: set[str] = set()
                for expr in clause.expressions or []:
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    binders = _local_binders(core)
                    for name in _refs(core, ignore=binders):
                        if name not in scope:
                            return _issue(
                                name, "Carry it through WITH or MATCH again"
                            )
                    an = _alias_name(expr)
                    if an:
                        ret_aliases.add(an)
                order_scope = scope | ret_aliases
                for sub in (clause.order, clause.skip, clause.limit):
                    for name in _refs(sub):
                        if name not in order_scope:
                            return _issue(
                                name,
                                "RETURN ORDER BY / SKIP / LIMIT use in-scope names",
                            )
        return []

    root = tree.this if isinstance(tree, a.Cypher) else tree
    if isinstance(root, a.Query):
        return _check_query(root)
    if isinstance(root, a.Union):
        issues: list[ConstraintIssue] = []
        for q in root.find_all(a.Query):
            assert isinstance(q, a.Query)
            issues.extend(_check_query(q))
            if issues:
                return issues
    return []
