"""Rewrite: FET-45 CASE null-guard around OPTIONAL scalar uses."""

from __future__ import annotations

from cypherast import ast as a

# Default empty — catalog / apply_capabilities pass caps.optional_risky_functions.
DEFAULT_OPTIONAL_RISKY_FUNCTIONS: frozenset[str] = frozenset()


def _optional_pattern_vars(tree: a.AstNode) -> set[str]:
    """Vars introduced by OPTIONAL MATCH and not later rebound as required."""

    def _query_root() -> a.Query | None:
        root = tree.this if isinstance(tree, a.Cypher) else tree
        return root if isinstance(root, a.Query) else None

    q = _query_root()
    if q is None:
        return set()

    optional_vars: set[str] = set()
    bound: set[str] = set()

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

    for clause in q.clauses or []:
        if isinstance(clause, a.Match):
            vars_here = _pattern_vars(clause.pattern)
            if clause.optional:
                for v in vars_here:
                    if v not in bound:
                        optional_vars.add(v)
                bound |= vars_here
            else:
                bound |= vars_here
                optional_vars -= vars_here
        elif isinstance(clause, a.With):
            nxt_opt: set[str] = set()
            nxt_bound: set[str] = set()
            for expr in clause.expressions or []:
                if isinstance(expr, a.Alias) and isinstance(expr.alias, a.Identifier):
                    alias = expr.alias.this
                    nxt_bound.add(alias)
                    if isinstance(expr.this, a.Identifier) and expr.this.this in optional_vars:
                        nxt_opt.add(alias)
                elif isinstance(expr, a.Identifier):
                    nxt_bound.add(expr.this)
                    if expr.this in optional_vars:
                        nxt_opt.add(expr.this)
            optional_vars, bound = nxt_opt, nxt_bound
    return optional_vars


def _optional_var_guarded(node: a.AstNode, var: str) -> bool:
    """True if ``node`` subtree has ``var IS NOT NULL`` or ``CASE WHEN var IS NULL``."""
    for n in node.find_all(a.IsNull):
        assert isinstance(n, a.IsNull)
        if _is_not_null_guard_for_var(n, var):
            return True
    for case in node.find_all(a.Case):
        assert isinstance(case, a.Case)
        for cond, _then in case.ifs or []:
            if (
                isinstance(cond, a.IsNull)
                and not cond.not_
                and isinstance(cond.this, a.Identifier)
                and cond.this.this == var
            ):
                return True
    return False


def _call_under_null_case_guard(call: a.AstNode, var: str) -> bool:
    """True if ``call`` is nested under ``CASE WHEN var IS NULL …``."""
    cur: a.AstNode | None = call
    while cur is not None:
        if isinstance(cur, a.Case):
            for cond, _then in cur.ifs or []:
                if (
                    isinstance(cond, a.IsNull)
                    and not cond.not_
                    and isinstance(cond.this, a.Identifier)
                    and cond.this.this == var
                ):
                    return True
        cur = cur.parent
    return False


def _is_not_null_guard_for_var(n: a.IsNull, var: str) -> bool:
    """True if ``n`` is ``var IS NOT NULL`` or ``id(var)/elementId(var) IS NOT NULL``."""
    if not n.not_:
        return False
    if isinstance(n.this, a.Identifier) and n.this.this == var:
        return True
    if isinstance(n.this, a.FunctionCall) and str(n.this.name).lower() in {"id", "elementid"}:
        for arg in n.this.expressions or []:
            if isinstance(arg, a.Identifier) and arg.this == var:
                return True
    return False


def _where_is_not_null_guard(tree: a.AstNode, var: str) -> bool:
    """True if a filtering WHERE requires ``var`` (or id(var)) IS NOT NULL.

    Disjunctive guards (``… OR …``) do not count — they do not force null exclusion.
    """
    for n in tree.find_all(a.IsNull):
        assert isinstance(n, a.IsNull)
        if not _is_not_null_guard_for_var(n, var):
            continue
        p: a.AstNode | None = n.parent
        ok = False
        while p is not None:
            if isinstance(p, (a.Or, a.Xor)):
                ok = False
                break
            if isinstance(p, a.Where):
                ok = True
                break
            p = p.parent
        if ok:
            return True
    return False


def _risky_optional_vars_in(
    expr: a.AstNode,
    optional_vars: set[str],
    *,
    risky_functions: frozenset[str],
) -> set[str]:
    hit: set[str] = set()
    for call in expr.find_all(a.FunctionCall):
        assert isinstance(call, a.FunctionCall)
        if str(call.name).lower() not in risky_functions:
            continue
        for n in call.walk():
            if isinstance(n, a.Identifier) and n.this in optional_vars:
                hit.add(n.this)
    return hit


def guard_optional_scalar_use(
    tree: a.AstNode,
    *,
    risky_functions: frozenset[str] | None = None,
) -> a.AstNode:
    """Wrap RETURN/WITH exprs that use OPTIONAL vars in id()/split/… with null CASE.

    ``CASE WHEN dl IS NULL THEN NULL ELSE <expr> END`` (FET-45 safe form).

    When ``risky_functions`` is None, uses ``DEFAULT_OPTIONAL_RISKY_FUNCTIONS``
    (empty). Dialects pass ``caps.optional_risky_functions`` via catalog/apply.
    """
    risky = DEFAULT_OPTIONAL_RISKY_FUNCTIONS if risky_functions is None else risky_functions
    if not risky:
        return tree
    optional_vars = _optional_pattern_vars(tree)
    if not optional_vars:
        return tree

    def _wrap(expr: a.AstNode) -> a.AstNode:
        needed = _risky_optional_vars_in(expr, optional_vars, risky_functions=risky)
        if not needed:
            return expr
        # Skip if every needed var already has a null guard somewhere on the expr
        if all(_optional_var_guarded(expr, v) for v in needed):
            return expr
        core = expr.this if isinstance(expr, a.Alias) else expr
        alias = expr.alias if isinstance(expr, a.Alias) else None
        # Already a null-guard CASE at the root — leave it
        if isinstance(core, a.Case) and all(_optional_var_guarded(core, v) for v in needed):
            return expr
        ifs = [(a.IsNull(this=a.Identifier(this=v)), a.Null()) for v in sorted(needed)]
        wrapped = a.Case(this=None, ifs=ifs, default=core)
        if alias is not None:
            return a.Alias(this=wrapped, alias=alias)
        return wrapped

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, (a.With, a.Return)) and node.expressions:
            node.expressions = [_wrap(e) for e in node.expressions]
        return node

    return tree.transform(_fix, copy=False)
