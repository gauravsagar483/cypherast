"""Validate: mismatched CASE THEN/ELSE arm shapes (ET-16/ET-17)."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue
from cypherast.schema import lookup_function

_LIST_RETURN_FUNCS = frozenset(
    {
        "collect",
        "keys",
        "labels",
        "range",
        "split",
        "tail",
        "nodes",
        "relationships",
        "allshortestpaths",
    }
)
_MAP_RETURN_FUNCS = frozenset({"properties"})


def _case_arm_kind(
    expr: a.AstNode | None,
    list_aliases: set[str],
    map_aliases: set[str],
) -> str:
    """Classify a CASE result arm for PuppyGraph ET-16/ET-17 checks.

    Returns one of: null, list_lit, list, map_lit, map, scalar, unknown.
    """
    if expr is None or isinstance(expr, a.Null):
        return "null"
    if isinstance(expr, a.List):
        return "list_lit"
    if isinstance(expr, a.Map):
        return "map_lit"
    if isinstance(expr, a.MapProjection):
        return "map"
    if isinstance(expr, a.FunctionCall):
        name = str(expr.name).lower()
        if name in _LIST_RETURN_FUNCS:
            return "list"
        if name in _MAP_RETURN_FUNCS:
            return "map"
        sig = lookup_function(name)
        if sig:
            rt = sig[1]
            if rt == "list":
                return "list"
            if rt == "map":
                return "map"
            if rt in {"integer", "float", "number", "string", "boolean", "node", "path"}:
                return "scalar"
        return "unknown"
    if isinstance(expr, a.Identifier):
        name = str(expr.this or "")
        if name in list_aliases:
            return "list"
        if name in map_aliases:
            return "map"
        return "unknown"
    if isinstance(
        expr,
        (
            a.Integer,
            a.Float,
            a.String,
            a.Boolean,
            a.Property,
            a.Parameter,
        ),
    ):
        return "scalar"
    if isinstance(expr, a.Alias):
        return _case_arm_kind(expr.this, list_aliases, map_aliases)
    return "unknown"


def _case_arm_family(kind: str) -> str:
    if kind in {"list", "list_lit"}:
        return "list"
    if kind in {"map", "map_lit"}:
        return "map"
    return kind


def _case_arms_compatible(left: str, right: str) -> bool:
    if left == "null" or right == "null":
        return True
    if left == "unknown" or right == "unknown":
        return True
    fl, fr = _case_arm_family(left), _case_arm_family(right)
    if fl != fr:
        return False
    # ET-16 / ET-17: list var/collect vs list literal (and map var vs map lit)
    if {left, right} == {"list", "list_lit"}:
        return False
    return {left, right} != {"map", "map_lit"}


def _register_projection_aliases(
    expressions: list[a.AstNode] | None,
    list_aliases: set[str],
    map_aliases: set[str],
) -> None:
    if not expressions:
        return
    # WITH without * replaces scope — drop prior aliases when no star
    has_star = any(isinstance(e, a.Star) for e in expressions) or any(
        isinstance(e, a.Alias) and isinstance(e.this, a.Star) for e in expressions
    )
    if not has_star:
        list_aliases.clear()
        map_aliases.clear()
    for expr in expressions:
        if not isinstance(expr, a.Alias):
            continue
        alias = expr.alias
        name = (
            str(alias.this)
            if isinstance(alias, a.Identifier)
            else str(alias)
            if isinstance(alias, str)
            else None
        )
        if not name:
            continue
        kind = _case_arm_kind(expr.this, list_aliases, map_aliases)
        fam = _case_arm_family(kind)
        if fam == "list":
            list_aliases.add(name)
            map_aliases.discard(name)
        elif fam == "map":
            map_aliases.add(name)
            list_aliases.discard(name)


def _mismatched_case_arms(tree: a.AstNode) -> list[ConstraintIssue]:
    """PuppyGraph ET-16/ET-17: incompatible CASE THEN/ELSE arm shapes."""
    list_aliases: set[str] = set()
    map_aliases: set[str] = set()
    issues: list[ConstraintIssue] = []

    def _check_case(case: a.Case) -> None:
        kinds: list[str] = []
        for pair in case.ifs or []:
            if not isinstance(pair, (tuple, list)) or len(pair) < 2:
                continue
            then = pair[1]
            if then is not None:
                kinds.append(_case_arm_kind(then, list_aliases, map_aliases))
        if case.default is not None:
            kinds.append(_case_arm_kind(case.default, list_aliases, map_aliases))
        kinds = [k for k in kinds if k != "null"]
        for i, ki in enumerate(kinds):
            for kj in kinds[i + 1 :]:
                if _case_arms_compatible(ki, kj):
                    continue
                issues.append(
                    ConstraintIssue(
                        "CG1401",
                        f"CASE arms mix incompatible types ({ki} vs {kj})",
                        hint=(
                            "PuppyGraph [ET-17]: THEN/ELSE must share a compatible "
                            "shape — do not CASE a collected list with a literal "
                            "list/map/scalar; return the list directly or use null"
                        ),
                    )
                )
                return

    def _check_cases_under(node: a.AstNode) -> None:
        for case in node.find_all(a.Case):
            assert isinstance(case, a.Case)
            _check_case(case)

    def _walk(node: a.AstNode) -> None:
        if isinstance(node, a.Cypher) and node.this is not None:
            _walk(node.this)
            return
        if isinstance(node, a.Query):
            for clause in node.clauses or []:
                _walk(clause)
            return
        if isinstance(node, a.Union):
            for part in (node.this, node.expression):
                if part is None:
                    continue
                saved_l = set(list_aliases)
                saved_m = set(map_aliases)
                list_aliases.clear()
                map_aliases.clear()
                _walk(part)
                list_aliases.clear()
                map_aliases.clear()
                list_aliases.update(saved_l)
                map_aliases.update(saved_m)
            return
        if isinstance(node, a.With):
            # WITH projections see prior aliases; then replace scope
            _check_cases_under(node)
            _register_projection_aliases(node.expressions, list_aliases, map_aliases)
            return
        if isinstance(node, a.Return):
            _check_cases_under(node)
            return
        if isinstance(node, a.Unwind):
            _check_cases_under(node)
            if isinstance(node.alias, a.Identifier) and node.alias.this:
                name = str(node.alias.this)
                list_aliases.discard(name)
                map_aliases.discard(name)
            return
        _check_cases_under(node)

    root = tree.this if isinstance(tree, a.Cypher) else tree
    _walk(root)
    return issues
