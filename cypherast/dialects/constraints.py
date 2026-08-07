"""Generic dialect constraint rewrites + validators (engine-agnostic helpers).

Callers pass a ``DialectCapabilities`` snapshot. Label names come from
``GraphSchema`` only — never hard-coded domain vocabulary here.
"""

from __future__ import annotations

from dataclasses import dataclass

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.errors import ValidationError
from cypherast.schema import GraphSchema, RelTypeDef, ensure_schema


@dataclass(frozen=True, slots=True)
class ConstraintIssue:
    code: str
    message: str
    hint: str | None = None


def apply_capabilities(
    tree: a.AstNode,
    caps: DialectCapabilities,
    *,
    schema: object | None = None,
) -> a.AstNode:
    """Rewrite tree to satisfy capability constraints where auto-fix is safe."""
    node = tree
    if caps.require_labelled_nodes:
        node = ensure_labelled_nodes(node, schema=schema)
    if caps.rewrite_var_length_bounds and (
        caps.max_var_length_hops is not None or not caps.allow_unbounded_var_length
    ):
        node = bound_variable_length(
            node,
            max_hops=caps.max_var_length_hops or 5,
            allow_unbounded=caps.allow_unbounded_var_length,
        )
    if not caps.allow_cartesian_match_paths and caps.rewrite_cartesian_match_paths:
        node = split_multi_path_match(node)
    if (
        not caps.allow_distinct_with_aggregate
        and caps.rewrite_distinct_beside_aggregate
    ):
        node = drop_distinct_beside_aggregate(node)
    if (
        caps.rewrite_collect_distinct_cap
        and caps.max_collect_distinct_per_clause is not None
    ):
        node = cap_collect_distinct(node, max_n=caps.max_collect_distinct_per_clause)
    if not caps.allow_nulls_order_modifiers:
        node = strip_nulls_order_modifiers(node)
    if caps.rewrite_unguarded_optional_scalar_use:
        node = guard_optional_scalar_use(node)
    return node


def validate_capabilities(
    tree: a.AstNode,
    caps: DialectCapabilities,
    *,
    schema: object | None = None,
) -> list[ConstraintIssue]:
    """Report remaining violations (after or instead of rewrite).

    Prefer ``optimize(..., write=dialect)`` then ``validate`` — raw validate
    may still flag constructs optimize rewrites (e.g. Cartesian MATCH).

    When ``schema`` is a ``GraphSchema``, also checks property access against
    declared labels/rel types (id-fields → CG1305; undeclared props when
    ``schema.strict`` → CG1303).
    """
    issues: list[ConstraintIssue] = []
    if caps.require_labelled_nodes:
        issues.extend(_unlabelled_nodes(tree))
    if not caps.allow_cartesian_match_paths:
        issues.extend(_cartesian_matches(tree))
    if caps.max_var_length_hops is not None or not caps.allow_unbounded_var_length:
        issues.extend(
            _bad_var_length(
                tree,
                max_hops=caps.max_var_length_hops or 5,
                allow_unbounded=caps.allow_unbounded_var_length,
            )
        )
    if not caps.allow_list_comprehension and tree.find(a.ListComprehension):
        issues.append(
            ConstraintIssue(
                "CG1401",
                "List comprehensions are not supported by this dialect",
                hint="Extract in WITH/MATCH, then collect(DISTINCT scalar) or count(DISTINCT …)",
            )
        )
    if not caps.allow_pattern_comprehension and tree.find(a.PatternComprehension):
        issues.append(
            ConstraintIssue(
                "CG1401",
                "Pattern comprehensions are not supported by this dialect",
                hint="Expand to MATCH / OPTIONAL MATCH + projection",
            )
        )
    if not caps.allow_list_concat:
        issues.extend(_list_concat_ops(tree))
    if not caps.allow_node_in_list_membership:
        issues.extend(_node_in_list_membership(tree))
    if not caps.allow_id_in_string_predicates:
        issues.extend(_id_in_string_predicates(tree))
    if not caps.allow_unguarded_optional_scalar_use:
        issues.extend(_unguarded_optional_scalar_use(tree))
    if not caps.allow_nulls_order_modifiers:
        issues.extend(_nulls_order_modifiers(tree))
    if not caps.allow_exists_function:
        issues.extend(_exists_function_calls(tree))
    if not caps.allow_distinct_with_aggregate:
        issues.extend(_distinct_with_aggregate(tree))
    if caps.max_collect_distinct_per_clause is not None:
        issues.extend(
            _too_many_collect_distinct(tree, caps.max_collect_distinct_per_clause)
        )
    if not caps.allow_collect_distinct_with_other_aggregates:
        issues.extend(_collect_distinct_with_other_aggregates(tree))
    if caps.require_matching_union_columns:
        issues.extend(_union_column_mismatch(tree))
    if caps.check_undefined_variables:
        issues.extend(_undefined_variables(tree))
    if not caps.pattern_predicate_introduces_bindings:
        issues.extend(_pattern_predicate_bindings(tree))
    gs = ensure_schema(schema)
    if gs is not None:
        issues.extend(_schema_property_access(tree, gs))
    return issues


def raise_if_invalid(
    tree: a.AstNode,
    caps: DialectCapabilities,
    *,
    schema: object | None = None,
) -> None:
    issues = validate_capabilities(tree, caps, schema=schema)
    if not issues:
        return
    first = issues[0]
    raise ValidationError(
        first.message,
        code=first.code
        if first.code
        in {
            "CG1201",
            "CG1202",
            "CG1203",
            "CG1301",
            "CG1302",
            "CG1303",
            "CG1304",
            "CG1305",
            "CG1401",
            "CG1402",
        }
        else "CG1401",
        hint=first.hint or (f"+{len(issues) - 1} more" if len(issues) > 1 else None),
    )


# --- rewrites -----------------------------------------------------------------


def bound_variable_length(
    tree: a.AstNode, *, max_hops: int, allow_unbounded: bool
) -> a.AstNode:
    def _fix(node: a.AstNode) -> a.AstNode | None:
        if not isinstance(node, a.RelationshipPattern) or not node.variable_length:
            return node
        hi = node.max_hops
        if hi is None and not allow_unbounded or hi is not None and hi > max_hops:
            node.max_hops = max_hops
        if node.min_hops is None:
            node.min_hops = 0
        return node

    return tree.transform(_fix, copy=False)


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


def drop_distinct_beside_aggregate(tree: a.AstNode) -> a.AstNode:
    """``WITH/RETURN DISTINCT …, count(…)`` → drop DISTINCT (grouping already implied)."""

    def _has_agg(expressions: list[a.AstNode] | None) -> bool:
        for expr in expressions or []:
            node = expr.this if isinstance(expr, a.Alias) else expr
            if isinstance(node, a.FunctionCall) and str(node.name).lower() in {
                "count",
                "sum",
                "avg",
                "min",
                "max",
                "collect",
            }:
                return True
        return False

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, (a.With, a.Return)) and node.distinct and _has_agg(
            node.expressions
        ):
            node.distinct = None
        return node

    return tree.transform(_fix, copy=False)


def ensure_labelled_nodes(
    tree: a.AstNode,
    schema: object | None = None,
) -> a.AstNode:
    """Fill missing MATCH node labels from schema + labels already in the query.

    1. Seed a working ``GraphSchema`` from ``schema`` (if any).
    2. Mine ``(Lab)-[:R]->(Lab)`` segments in this tree into that schema.
    3. Infer missing ends from typed relationships (fixpoint).

    Always runs (even when caller schema has no rel_types) so lineage-style
    queries that already name labels on some clauses can label the rest.
    """
    base = schema if isinstance(schema, GraphSchema) else GraphSchema()
    # Shallow working copy of rel endpoints (do not mutate caller schema)
    gs = GraphSchema()
    gs.labels = dict(base.labels)
    for name, rd in base.rel_types.items():
        gs.rel_types[name] = RelTypeDef(
            name=rd.name,
            properties=dict(rd.properties),
            endpoints=list(rd.endpoints),
        )

    counter = {"n": 0}

    def _name() -> str:
        counter["n"] += 1
        return f"_n_{counter['n']}"

    def _existing_labels(n: a.NodePattern) -> set[str]:
        if not isinstance(n.labels, a.LabelExpression):
            return set()
        if n.labels.expression:
            # OR expression person|software — treat as labelled, not expandable here
            return {str(n.labels.expression)}
        if n.labels.labels:
            return {str(x) for x in n.labels.labels}
        return set()

    def _apply_labels(n: a.NodePattern, cands: set[str]) -> bool:
        # Ignore OR-expression markers stored as single joined string with |
        clean = {c for c in cands if c and "|" not in c}
        if not clean or _existing_labels(n):
            return False
        # Drop expression-only "labelled" that was only a marker — if expression set, skip
        if isinstance(n.labels, a.LabelExpression) and n.labels.expression:
            return False
        if len(clean) == 1:
            n.labels = a.LabelExpression(labels=[next(iter(clean))])
        else:
            n.labels = a.LabelExpression(
                labels=[],
                expression="|".join(sorted(clean)),
            )
        if n.variable is None:
            n.variable = a.Identifier(this=_name())
        return True

    def _rel_def(tname: str) -> RelTypeDef | None:
        rd = gs.rel_types.get(tname) or gs.rel_types.get(tname.lower())
        if rd is not None:
            return rd
        for k, v in gs.rel_types.items():
            if k.lower() == tname.lower():
                return v
        return None

    def _ensure_rel(tname: str) -> RelTypeDef:
        rd = _rel_def(tname)
        if rd is not None:
            return rd
        rd = RelTypeDef(name=tname)
        gs.rel_types[tname] = rd
        return rd

    def _mine_path(path: a.PathPattern) -> None:
        els = list(path.elements or [])
        i = 0
        while i + 2 < len(els):
            left, rel, right = els[i], els[i + 1], els[i + 2]
            if not (
                isinstance(left, a.NodePattern)
                and isinstance(rel, a.RelationshipPattern)
                and isinstance(right, a.NodePattern)
            ):
                i += 1
                continue
            types = [str(t) for t in (rel.types or [])]
            left_labs = {x for x in _existing_labels(left) if "|" not in x}
            right_labs = {x for x in _existing_labels(right) if "|" not in x}
            if types and left_labs and right_labs:
                d = rel.direction
                for tname in types:
                    rd = _ensure_rel(tname)
                    for ls in left_labs:
                        for rs in right_labs:
                            # OUTGOING and BOTH: record left→right as start→end
                            pair = (
                                (rs, ls)
                                if d is a.Direction.INCOMING
                                else (ls, rs)
                            )
                            if pair not in rd.endpoints:
                                rd.endpoints.append(pair)
            i += 2

    def _endpoints(types: list[str]) -> tuple[set[str], set[str]]:
        starts: set[str] = set()
        ends: set[str] = set()
        for tname in types:
            rd = _rel_def(tname)
            if rd is None:
                continue
            for s, e in rd.endpoints:
                starts.add(s)
                ends.add(e)
        return starts, ends

    def _infer_path(path: a.PathPattern) -> bool:
        changed = False
        els = list(path.elements or [])
        i = 0
        while i + 2 < len(els):
            left, rel, right = els[i], els[i + 1], els[i + 2]
            if not (
                isinstance(left, a.NodePattern)
                and isinstance(rel, a.RelationshipPattern)
                and isinstance(right, a.NodePattern)
            ):
                i += 1
                continue
            types = [str(t) for t in (rel.types or [])]
            if not types:
                i += 2
                continue
            starts, ends = _endpoints(types)
            left_labs = {x for x in _existing_labels(left) if "|" not in x}
            right_labs = {x for x in _existing_labels(right) if "|" not in x}

            if left_labs:
                left_l = {x.lower() for x in left_labs}
                narrowed_ends: set[str] = set()
                for tname in types:
                    rd = _rel_def(tname)
                    if rd is None:
                        continue
                    for s, e in rd.endpoints:
                        if s.lower() in left_l:
                            narrowed_ends.add(e)
                if narrowed_ends:
                    ends = narrowed_ends
            if right_labs:
                right_l = {x.lower() for x in right_labs}
                narrowed_starts: set[str] = set()
                for tname in types:
                    rd = _rel_def(tname)
                    if rd is None:
                        continue
                    for s, e in rd.endpoints:
                        if e.lower() in right_l:
                            narrowed_starts.add(s)
                if narrowed_starts:
                    starts = narrowed_starts

            d = rel.direction
            if d is a.Direction.OUTGOING:
                changed |= _apply_labels(left, starts)
                changed |= _apply_labels(right, ends)
            elif d is a.Direction.INCOMING:
                changed |= _apply_labels(left, ends)
                changed |= _apply_labels(right, starts)
            else:
                if starts == ends and len(starts) == 1:
                    changed |= _apply_labels(left, starts)
                    changed |= _apply_labels(right, ends)
                elif left_labs and not right_labs:
                    changed |= _apply_labels(right, ends if ends else starts)
                elif right_labs and not left_labs:
                    changed |= _apply_labels(left, starts if starts else ends)
                elif not left_labs and not right_labs and len(starts | ends) == 1:
                    one = starts | ends
                    changed |= _apply_labels(left, one)
                    changed |= _apply_labels(right, one)

            # Fallback when schema/mining had no endpoints: copy labels from the
            # labelled neighbor so PuppyGraph gets a labelled pattern instead of
            # CG1402 (e.g. (a:Metric)-[:DERIVED_FROM]->(b) → (b:Metric)).
            left_labs = {x for x in _existing_labels(left) if "|" not in x}
            right_labs = {x for x in _existing_labels(right) if "|" not in x}
            if not _existing_labels(right) and left_labs:
                changed |= _apply_labels(right, left_labs)
            if not _existing_labels(left) and right_labs:
                changed |= _apply_labels(left, right_labs)
            i += 2
        return changed

    paths: list[a.PathPattern] = []
    for match in tree.find_all(a.Match):
        assert isinstance(match, a.Match)
        if not isinstance(match.pattern, a.Pattern):
            continue
        for path in match.pattern.paths or []:
            if isinstance(path, a.PathPattern):
                paths.append(path)

    for path in paths:
        _mine_path(path)

    for _ in range(8):
        changed = False
        for path in paths:
            changed |= _infer_path(path)
        if changed:
            for path in paths:
                _mine_path(path)
        else:
            break
    return tree


def strip_nulls_order_modifiers(tree: a.AstNode) -> a.AstNode:
    """Drop ``NULLS FIRST/LAST`` when dialect forbids them."""

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, a.Ordered) and node.nulls:
            node.nulls = None
        return node

    return tree.transform(_fix, copy=False)


_OPTIONAL_RISKY_FNS = frozenset(
    {"id", "elementid", "split", "tostring", "tointeger", "tofloat", "size"}
)


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
        if n.not_ and isinstance(n.this, a.Identifier) and n.this.this == var:
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


def _where_is_not_null_guard(tree: a.AstNode, var: str) -> bool:
    """True if some ``WHERE`` contains ``var IS NOT NULL``."""
    for n in tree.find_all(a.IsNull):
        assert isinstance(n, a.IsNull)
        if not (
            n.not_
            and isinstance(n.this, a.Identifier)
            and n.this.this == var
        ):
            continue
        p: a.AstNode | None = n
        while p is not None:
            if isinstance(p, a.Where):
                return True
            p = p.parent
    return False


def _risky_optional_vars_in(expr: a.AstNode, optional_vars: set[str]) -> set[str]:
    hit: set[str] = set()
    for call in expr.find_all(a.FunctionCall):
        assert isinstance(call, a.FunctionCall)
        if str(call.name).lower() not in _OPTIONAL_RISKY_FNS:
            continue
        for n in call.walk():
            if isinstance(n, a.Identifier) and n.this in optional_vars:
                hit.add(n.this)
    return hit


def guard_optional_scalar_use(tree: a.AstNode) -> a.AstNode:
    """Wrap RETURN/WITH exprs that use OPTIONAL vars in id()/split/… with null CASE.

    ``CASE WHEN dl IS NULL THEN NULL ELSE <expr> END`` (FET-45 safe form).
    """
    optional_vars = _optional_pattern_vars(tree)
    if not optional_vars:
        return tree

    def _wrap(expr: a.AstNode) -> a.AstNode:
        needed = _risky_optional_vars_in(expr, optional_vars)
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
        ifs = [
            (a.IsNull(this=a.Identifier(this=v)), a.Null())
            for v in sorted(needed)
        ]
        wrapped = a.Case(this=None, ifs=ifs, default=core)
        if alias is not None:
            return a.Alias(this=wrapped, alias=alias)
        return wrapped

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, (a.With, a.Return)) and node.expressions:
            node.expressions = [_wrap(e) for e in node.expressions]
        return node

    return tree.transform(_fix, copy=False)


def cap_collect_distinct(tree: a.AstNode, *, max_n: int) -> a.AstNode:
    """If > max collect(DISTINCT) in one clause, convert extras to count(DISTINCT).

    Prefer leaving a single collect(DISTINCT) and rewriting additional ones to count.
    """

    def _rewrite_exprs(expressions: list[a.AstNode]) -> list[a.AstNode]:
        seen = 0
        out: list[a.AstNode] = []
        for expr in expressions:
            core = expr.this if isinstance(expr, a.Alias) else expr
            if (
                isinstance(core, a.FunctionCall)
                and str(core.name).lower() == "collect"
                and core.distinct
            ):
                seen += 1
                if seen > max_n:
                    replacement = a.FunctionCall(
                        name="count", expressions=list(core.expressions), distinct=True
                    )
                    if isinstance(expr, a.Alias):
                        out.append(a.Alias(this=replacement, alias=expr.alias))
                    else:
                        out.append(replacement)
                    continue
            out.append(expr)
        return out

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, (a.With, a.Return)) and node.expressions:
            node.expressions = _rewrite_exprs(list(node.expressions))
        return node

    return tree.transform(_fix, copy=False)


# --- validators ---------------------------------------------------------------


def _unlabelled_nodes(tree: a.AstNode) -> list[ConstraintIssue]:
    """MATCH/OPTIONAL MATCH nodes must be labelled on first bind.

    Bare ``(var)`` reuse is OK when ``var`` was already bound with a label
    earlier in the same query (after WITH, only projected labelled names remain).
    ``UNWIND collect(node) AS x`` then ``(x)`` counts as bound reuse.
    Anonymous ``()`` and new unlabelled ``(x)`` always fail.
    """
    issues: list[ConstraintIssue] = []
    labelled: set[str] = set()
    node_lists: set[str] = set()  # aliases of collect(labelled_node)

    def _label_names(n: a.NodePattern) -> list[str]:
        if isinstance(n.labels, a.LabelExpression):
            if n.labels.expression:
                return [str(n.labels.expression)]
            return list(n.labels.labels or [])
        return []

    def _collect_of_labelled(expr: a.AstNode) -> bool:
        core = expr.this if isinstance(expr, a.Alias) else expr
        if not isinstance(core, a.FunctionCall):
            return False
        if str(core.name).lower() != "collect":
            return False
        args = core.expressions or []
        if len(args) == 1 and isinstance(args[0], a.Identifier):
            return args[0].this in labelled
        return False

    def _alias_name(expr: a.AstNode) -> str | None:
        if isinstance(expr, a.Alias):
            if isinstance(expr.alias, a.Identifier):
                return str(expr.alias.this)
            if isinstance(expr.alias, str):
                return expr.alias
        return None

    def _check_match(match: a.Match) -> None:
        if not isinstance(match.pattern, a.Pattern):
            return
        for n in match.pattern.walk():
            if not isinstance(n, a.NodePattern):
                continue
            labels = _label_names(n)
            var = n.variable.this if isinstance(n.variable, a.Identifier) else None
            if labels:
                if var:
                    labelled.add(var)
                continue
            if var is not None and var in labelled:
                continue
            where = f"({var})" if var else "()"
            issues.append(
                ConstraintIssue(
                    "CG1402",
                    f"Unlabelled node pattern {where} is not allowed by this dialect",
                    hint="Write (var:Label) on first bind; never () or new (var) without a label",
                )
            )

    def _apply_with(clause: a.With) -> None:
        nonlocal labelled, node_lists
        nxt: set[str] = set()
        nxt_lists: set[str] = set()
        for expr in clause.expressions or []:
            alias = _alias_name(expr)
            if _collect_of_labelled(expr) and alias:
                nxt_lists.add(alias)
            if isinstance(expr, a.Alias):
                src = expr.this.this if isinstance(expr.this, a.Identifier) else None
                if src in labelled and alias:
                    nxt.add(alias)
                elif src in node_lists and alias:
                    nxt_lists.add(alias)
            elif isinstance(expr, a.Identifier):
                if expr.this in labelled:
                    nxt.add(expr.this)
                if expr.this in node_lists:
                    nxt_lists.add(expr.this)
        labelled = nxt
        node_lists = nxt_lists

    def _apply_unwind(clause: a.Unwind) -> None:
        nonlocal labelled
        alias = (
            clause.alias.this
            if isinstance(clause.alias, a.Identifier)
            else clause.alias
            if isinstance(clause.alias, str)
            else None
        )
        src = clause.expression
        from_list = (
            isinstance(src, a.Identifier) and src.this in node_lists
        ) or _collect_of_labelled(src)
        if alias and from_list:
            labelled.add(alias)

    root: a.AstNode | None = tree
    if isinstance(tree, a.Cypher) and isinstance(tree.this, a.Query):
        root = tree.this
    if isinstance(root, a.Query) and root.clauses:
        for clause in root.clauses:
            if isinstance(clause, a.Match):
                _check_match(clause)
            elif isinstance(clause, a.With):
                _apply_with(clause)
            elif isinstance(clause, a.Unwind):
                _apply_unwind(clause)
        return issues

    for match in tree.find_all(a.Match):
        assert isinstance(match, a.Match)
        _check_match(match)
    return issues


def _cartesian_matches(tree: a.AstNode) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    for n in tree.find_all(a.Match):
        assert isinstance(n, a.Match)
        if isinstance(n.pattern, a.Pattern) and len(n.pattern.paths or []) > 1:
            issues.append(
                ConstraintIssue(
                    "CG1401",
                    "Multiple paths in one MATCH are rejected (Cartesian risk)",
                    hint="Split into consecutive MATCH clauses sharing variables",
                )
            )
            break
    return issues


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


def _list_concat_ops(tree: a.AstNode) -> list[ConstraintIssue]:
    """ET-06: list concatenation via ``+`` (Add between list-ish operands)."""
    list_aliases: set[str] = set()
    list_fns = {
        "collect",
        "keys",
        "labels",
        "nodes",
        "relationships",
        "range",
        "split",
        "tail",
    }

    def _list_producing(n: a.AstNode | None) -> bool:
        if n is None:
            return False
        # Element / string index access is not a list operand
        if isinstance(n, a.ListSubscript):
            return False
        if isinstance(n, (a.List, a.ListComprehension)):
            return True
        if isinstance(n, a.FunctionCall) and str(n.name).lower() in list_fns:
            return True
        if isinstance(n, a.Identifier) and n.this in list_aliases:
            return True
        if isinstance(n, a.Add):
            return _list_producing(n.this) or _list_producing(n.expression)
        return False

    def _note_projection(expressions: list[a.AstNode] | None) -> None:
        for expr in expressions or []:
            if not isinstance(expr, a.Alias):
                continue
            alias = None
            if isinstance(expr.alias, a.Identifier):
                alias = expr.alias.this
            elif isinstance(expr.alias, str):
                alias = expr.alias
            if not alias:
                continue
            if _list_producing(expr.this):
                list_aliases.add(alias)
            else:
                list_aliases.discard(alias)

    def _scan_query(q: a.Query) -> list[ConstraintIssue]:
        nonlocal list_aliases
        list_aliases = set()
        for clause in q.clauses or []:
            if isinstance(clause, a.With):
                for expr in clause.expressions or []:
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    for add in core.find_all(a.Add) if hasattr(core, "find_all") else []:
                        assert isinstance(add, a.Add)
                        if _list_producing(add.this) or _list_producing(add.expression):
                            return [
                                ConstraintIssue(
                                    "CG1401",
                                    "List concatenation (+) is not supported by this dialect",
                                    hint="Avoid list + list; project with UNWIND / collect instead",
                                )
                            ]
                    # also top-level Add
                    if isinstance(core, a.Add) and (
                        _list_producing(core.this) or _list_producing(core.expression)
                    ):
                        return [
                            ConstraintIssue(
                                "CG1401",
                                "List concatenation (+) is not supported by this dialect",
                                hint="Avoid list + list; project with UNWIND / collect instead",
                            )
                        ]
                _note_projection(clause.expressions)
            elif isinstance(clause, a.Return):
                for expr in clause.expressions or []:
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    nodes = [core] if isinstance(core, a.Add) else []
                    if hasattr(core, "find_all"):
                        nodes.extend(core.find_all(a.Add))
                    for add in nodes:
                        assert isinstance(add, a.Add)
                        if _list_producing(add.this) or _list_producing(add.expression):
                            return [
                                ConstraintIssue(
                                    "CG1401",
                                    "List concatenation (+) is not supported by this dialect",
                                    hint="Avoid list + list; project with UNWIND / collect instead",
                                )
                            ]
        return []

    root = tree.this if isinstance(tree, a.Cypher) else tree
    if isinstance(root, a.Query):
        return _scan_query(root)
    if isinstance(root, a.Union):
        for q in root.find_all(a.Query):
            assert isinstance(q, a.Query)
            issues = _scan_query(q)
            if issues:
                return issues
        return []
    # Fallback: no alias tracking
    for n in tree.find_all(a.Add):
        assert isinstance(n, a.Add)
        if _list_producing(n.this) or _list_producing(n.expression):
            return [
                ConstraintIssue(
                    "CG1401",
                    "List concatenation (+) is not supported by this dialect",
                    hint="Avoid list + list; project with UNWIND / collect instead",
                )
            ]
    return []


def _node_in_list_membership(tree: a.AstNode) -> list[ConstraintIssue]:
    """ET-21: node variable on the left of ``IN`` (list membership)."""
    node_vars: set[str] = set()
    for n in tree.find_all(a.NodePattern):
        assert isinstance(n, a.NodePattern)
        if isinstance(n.variable, a.Identifier):
            node_vars.add(n.variable.this)

    def _listish_rhs(n: a.AstNode | None) -> bool:
        if n is None:
            return False
        if isinstance(n, (a.List, a.ListComprehension, a.ListSubscript)):
            return True
        if isinstance(n, a.Identifier):
            return True
        return isinstance(n, a.FunctionCall) and str(n.name).lower() in {
            "collect",
            "keys",
            "labels",
            "nodes",
            "relationships",
            "range",
            "split",
        }

    for n in tree.find_all(a.In):
        assert isinstance(n, a.In)
        left = n.this
        if isinstance(left, a.Identifier) and left.this in node_vars and _listish_rhs(
            n.expression
        ):
            return [
                ConstraintIssue(
                    "CG1401",
                    "Node IN list membership is not supported by this dialect",
                    hint="Compare on a property (n.id IN [...]) instead of the node itself",
                )
            ]
    return []


def _nulls_order_modifiers(tree: a.AstNode) -> list[ConstraintIssue]:
    for n in tree.find_all(a.Ordered):
        assert isinstance(n, a.Ordered)
        if n.nulls:
            return [
                ConstraintIssue(
                    "CG1401",
                    "ORDER BY NULLS FIRST/LAST is not supported by this dialect",
                    hint="Omit NULLS modifiers (optimize strips them when rewriting)",
                )
            ]
    return []


def _collect_distinct_with_other_aggregates(tree: a.AstNode) -> list[ConstraintIssue]:
    """TE-14: collect(DISTINCT) cannot sit beside other aggregates in one clause."""
    aggs = {"count", "sum", "avg", "min", "max", "collect"}
    for n in tree.find_all(a.With, a.Return):
        exprs = getattr(n, "expressions", None) or []
        cores: list[a.AstNode] = []
        for expr in exprs:
            cores.append(expr.this if isinstance(expr, a.Alias) else expr)
        has_collect_d = any(
            isinstance(c, a.FunctionCall)
            and str(c.name).lower() == "collect"
            and c.distinct
            for c in cores
        )
        if not has_collect_d:
            continue
        other = any(
            isinstance(c, a.FunctionCall)
            and str(c.name).lower() in aggs
            and not (str(c.name).lower() == "collect" and c.distinct)
            for c in cores
        )
        # TE-14: collect(DISTINCT) + any other aggregate (multi collect_d → APT-18)
        if other:
            return [
                ConstraintIssue(
                    "CG1401",
                    "collect(DISTINCT …) cannot combine with other aggregates in the same clause",
                    hint="Use only collect(DISTINCT) alone, or only count(DISTINCT …) tallies",
                )
            ]
    return []


def _id_in_string_predicates(tree: a.AstNode) -> list[ConstraintIssue]:
    """Bare id()/elementId() compared as a string (CONTAINS / STARTS/ENDS / = / <>)."""

    def _is_id_call(n: a.AstNode | None) -> bool:
        return (
            isinstance(n, a.FunctionCall)
            and str(n.name).lower() in {"id", "elementid"}
        )

    def _is_string_lit(n: a.AstNode | None) -> bool:
        return isinstance(n, a.String) or (
            isinstance(n, a.Literal) and isinstance(getattr(n, "this", None), str)
        )

    for n in tree.find_all(a.Contains, a.StartsWith, a.EndsWith):
        left = getattr(n, "this", None)
        if _is_id_call(left):
            return [
                ConstraintIssue(
                    "CG1401",
                    "id()/elementId() is not a string; wrap with toString(...) for text predicates",
                    hint="WHERE toString(id(m)) CONTAINS '…' or match a schema string property",
                )
            ]
    for n in tree.find_all(a.EQ, a.NEQ):
        assert isinstance(n, (a.EQ, a.NEQ))
        if _is_id_call(n.this) and _is_string_lit(n.expression):
            return [
                ConstraintIssue(
                    "CG1401",
                    "id()/elementId() cannot equal a string key; use toString(id(n)) or a property",
                    hint="WHERE toString(id(n)) = '…' or n.key = '…'",
                )
            ]
        if _is_string_lit(n.this) and _is_id_call(n.expression):
            return [
                ConstraintIssue(
                    "CG1401",
                    "id()/elementId() cannot equal a string key; use toString(id(n)) or a property",
                    hint="WHERE toString(id(n)) = '…' or n.key = '…'",
                )
            ]
    return []


def _unguarded_optional_scalar_use(tree: a.AstNode) -> list[ConstraintIssue]:
    """FET-45: OPTIONAL-bound vars in id()/split/… without a null guard."""
    optional_vars = _optional_pattern_vars(tree)
    if not optional_vars:
        return []

    for call in tree.find_all(a.FunctionCall):
        assert isinstance(call, a.FunctionCall)
        if str(call.name).lower() not in _OPTIONAL_RISKY_FNS:
            continue
        for n in call.walk():
            if not (isinstance(n, a.Identifier) and n.this in optional_vars):
                continue
            var = n.this
            if _call_under_null_case_guard(call, var):
                continue
            if _where_is_not_null_guard(tree, var):
                continue
            return [
                ConstraintIssue(
                    "CG1401",
                    f"OPTIONAL-bound `{var}` used in {call.name}() without null guard",
                    hint=(
                        f"Add CASE WHEN {var} IS NULL THEN NULL ELSE … END "
                        f"or WHERE {var} IS NOT NULL"
                    ),
                )
            ]
    return []


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


def _undefined_variables(tree: a.AstNode) -> list[ConstraintIssue]:
    """Flag identifiers used after WITH without being projected (e.g. ET-17 scope)."""

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

    def _check_query(q: a.Query) -> list[ConstraintIssue]:
        scope: set[str] = set()
        for clause in q.clauses or []:
            if isinstance(clause, (a.Match, a.Create, a.Merge)):
                _add_pattern_vars(clause.pattern, scope)
                where = getattr(clause, "where", None)
                binders = _pattern_pred_binders(where)
                for name in _refs(where, ignore=binders):
                    if name not in scope:
                        return [
                            ConstraintIssue(
                                "CG1401",
                                f"Variable `{name}` is not defined in this scope",
                                hint="Project it in WITH or reintroduce via MATCH",
                            )
                        ]
            elif isinstance(clause, a.With):
                for expr in clause.expressions or []:
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    binders = _pattern_pred_binders(core)
                    for name in _refs(core, ignore=binders):
                        if name not in scope:
                            return [
                                ConstraintIssue(
                                    "CG1401",
                                    f"Variable `{name}` is not defined in this scope",
                                    hint="Project it in a prior WITH or MATCH",
                                )
                            ]
                nxt: set[str] = set()
                for expr in clause.expressions or []:
                    an = _alias_name(expr)
                    if an:
                        nxt.add(an)
                where_scope = set(nxt)
                binders = _pattern_pred_binders(clause.where)
                for name in _refs(clause.where, ignore=binders):
                    if (
                        name not in where_scope
                        and name not in nxt
                        and name not in scope
                    ):
                        return [
                            ConstraintIssue(
                                "CG1401",
                                f"Variable `{name}` is not defined in this scope",
                                hint="WITH WHERE uses projected aliases",
                            )
                        ]
                for sub in (clause.order, clause.skip, clause.limit):
                    for name in _refs(sub):
                        if name not in nxt:
                            return [
                                ConstraintIssue(
                                    "CG1401",
                                    f"Variable `{name}` is not defined in this scope",
                                    hint="WITH ORDER BY / SKIP / LIMIT use projected aliases",
                                )
                            ]
                scope = nxt
            elif isinstance(clause, a.Unwind):
                for name in _refs(clause.expression):
                    if name not in scope:
                        return [
                            ConstraintIssue(
                                "CG1401",
                                f"Variable `{name}` is not defined in this scope",
                                hint="Project it before UNWIND",
                            )
                        ]
                if isinstance(clause.alias, a.Identifier):
                    scope.add(clause.alias.this)
                elif isinstance(clause.alias, str):
                    scope.add(clause.alias)
            elif isinstance(clause, a.Return):
                ret_aliases: set[str] = set()
                for expr in clause.expressions or []:
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    binders = _pattern_pred_binders(core)
                    for name in _refs(core, ignore=binders):
                        if name not in scope:
                            return [
                                ConstraintIssue(
                                    "CG1401",
                                    f"Variable `{name}` is not defined in this scope",
                                    hint="Carry it through WITH or MATCH again",
                                )
                            ]
                    an = _alias_name(expr)
                    if an:
                        ret_aliases.add(an)
                order_scope = scope | ret_aliases
                for sub in (clause.order, clause.skip, clause.limit):
                    for name in _refs(sub):
                        if name not in order_scope:
                            return [
                                ConstraintIssue(
                                    "CG1401",
                                    f"Variable `{name}` is not defined in this scope",
                                    hint="RETURN ORDER BY / SKIP / LIMIT use in-scope names",
                                )
                            ]
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


def _exists_function_calls(tree: a.AstNode) -> list[ConstraintIssue]:
    for n in tree.find_all(a.FunctionCall):
        assert isinstance(n, a.FunctionCall)
        if str(n.name).lower() == "exists":
            return [
                ConstraintIssue(
                    "CG1401",
                    "exists() is not supported by this dialect",
                    hint="Use a bare pattern predicate: WHERE NOT (a)-[:R]->(b)",
                )
            ]
    # EXISTS (path) as PatternPredicate(not_=False) — renderer handles; flag if Query form
    return []


def _distinct_with_aggregate(tree: a.AstNode) -> list[ConstraintIssue]:
    for n in tree.find_all(a.With, a.Return):
        if not getattr(n, "distinct", None):
            continue
        for expr in getattr(n, "expressions", None) or []:
            core = expr.this if isinstance(expr, a.Alias) else expr
            if isinstance(core, a.FunctionCall) and str(core.name).lower() in {
                "count",
                "sum",
                "avg",
                "min",
                "max",
                "collect",
            }:
                return [
                    ConstraintIssue(
                        "CG1401",
                        "DISTINCT cannot combine with aggregates in the same clause",
                        hint="WITH DISTINCT keys first (no agg), then aggregate in the next WITH",
                    )
                ]
    return []


def _too_many_collect_distinct(tree: a.AstNode, max_n: int) -> list[ConstraintIssue]:
    for n in tree.find_all(a.With, a.Return):
        count = 0
        for expr in getattr(n, "expressions", None) or []:
            core = expr.this if isinstance(expr, a.Alias) else expr
            if (
                isinstance(core, a.FunctionCall)
                and str(core.name).lower() == "collect"
                and core.distinct
            ):
                count += 1
        if count > max_n:
            return [
                ConstraintIssue(
                    "CG1401",
                    f"At most {max_n} collect(DISTINCT …) per WITH/RETURN",
                    hint="Use count(DISTINCT …) for extra tallies, or one string-collect per clause",
                )
            ]
    return []


def _schema_property_access(
    tree: a.AstNode, schema: GraphSchema
) -> list[ConstraintIssue]:
    """Reject id-field / undeclared property access when labels/types are known.

    Id-field markers always reject (``n.id_col`` → use ``id(n)``). Undeclared
    properties reject only when ``schema.strict`` and the label/rel is in schema.
    Unknown labels/types are ignored (no invented domain vocabulary).
    """

    def _label_names(n: a.NodePattern) -> list[str]:
        if isinstance(n.labels, a.LabelExpression):
            if n.labels.expression:
                return [str(n.labels.expression)]
            return [str(x) for x in (n.labels.labels or [])]
        return []

    def _alias_name(expr: a.AstNode) -> str | None:
        if isinstance(expr, a.Alias):
            if isinstance(expr.alias, a.Identifier):
                return str(expr.alias.this)
            if isinstance(expr.alias, str):
                return expr.alias
        if isinstance(expr, a.Identifier):
            return str(expr.this)
        return None

    def _bind_pattern(
        pattern: a.AstNode | None,
        node_vars: dict[str, set[str]],
        rel_vars: dict[str, set[str]],
    ) -> None:
        if pattern is None:
            return
        for n in pattern.walk():
            if isinstance(n, a.NodePattern):
                labs = {x for x in _label_names(n) if "|" not in x}
                if isinstance(n.variable, a.Identifier) and labs:
                    node_vars.setdefault(n.variable.this, set()).update(labs)
            elif isinstance(n, a.RelationshipPattern):
                types = {str(t) for t in (n.types or []) if t}
                if isinstance(n.variable, a.Identifier) and types:
                    rel_vars.setdefault(n.variable.this, set()).update(types)

    def _check_prop_against_labels(
        var: str, prop: str, labels: set[str]
    ) -> ConstraintIssue | None:
        known = [lb for lb in labels if schema.has_label(lb)]
        if not known:
            return None
        if any(schema.is_id_property(lb, prop) for lb in known):
            return ConstraintIssue(
                "CG1305",
                f"`{var}.{prop}` is an id field, not a map property",
                hint=f"Use id({var}) or elementId({var}) instead of {var}.{prop}",
            )
        if schema.strict and not any(schema.has_property(lb, prop) for lb in known):
            return ConstraintIssue(
                "CG1303",
                f"Unknown property `{prop}` on label(s) {', '.join(sorted(known))}",
                hint="Declare it on GraphSchema or remove the access",
            )
        return None

    def _check_prop_against_rels(
        var: str, prop: str, types: set[str]
    ) -> ConstraintIssue | None:
        known = [rt for rt in types if schema.has_rel(rt)]
        if not known:
            return None
        if any(schema.is_rel_id_property(rt, prop) for rt in known):
            return ConstraintIssue(
                "CG1305",
                f"`{var}.{prop}` is an id field, not a map property",
                hint=f"Use id({var}) or elementId({var}) instead of {var}.{prop}",
            )
        if schema.strict and not any(schema.has_rel_property(rt, prop) for rt in known):
            return ConstraintIssue(
                "CG1303",
                f"Unknown property `{prop}` on relationship type(s) "
                f"{', '.join(sorted(known))}",
                hint="Declare it on GraphSchema or remove the access",
            )
        return None

    def _map_keys(props: a.AstNode | None) -> list[str]:
        if not isinstance(props, a.Map):
            return []
        keys: list[str] = []
        for entry in props.entries or []:
            if isinstance(entry, tuple) and entry:
                keys.append(str(entry[0]))
            elif isinstance(entry, str):
                keys.append(entry)
        return keys

    def _check_inline_maps(pattern: a.AstNode | None) -> list[ConstraintIssue]:
        out: list[ConstraintIssue] = []
        if pattern is None:
            return out
        for n in pattern.walk():
            if isinstance(n, a.NodePattern):
                labs = {x for x in _label_names(n) if "|" not in x}
                var = n.variable.this if isinstance(n.variable, a.Identifier) else "?"
                for key in _map_keys(n.properties):
                    issue = _check_prop_against_labels(var, key, labs)
                    if issue:
                        out.append(issue)
            elif isinstance(n, a.RelationshipPattern):
                types = {str(t) for t in (n.types or []) if t}
                var = n.variable.this if isinstance(n.variable, a.Identifier) else "?"
                for key in _map_keys(n.properties):
                    issue = _check_prop_against_rels(var, key, types)
                    if issue:
                        out.append(issue)
        return out

    def _scan_props(
        node: a.AstNode | None,
        node_vars: dict[str, set[str]],
        rel_vars: dict[str, set[str]],
    ) -> list[ConstraintIssue]:
        if node is None:
            return []
        out: list[ConstraintIssue] = []
        for p in node.find_all(a.Property):
            assert isinstance(p, a.Property)
            if not isinstance(p.this, a.Identifier):
                continue
            var = p.this.this
            prop = str(p.name)
            if var in node_vars:
                issue = _check_prop_against_labels(var, prop, node_vars[var])
                if issue:
                    out.append(issue)
                    continue
            if var in rel_vars:
                issue = _check_prop_against_rels(var, prop, rel_vars[var])
                if issue:
                    out.append(issue)
        return out

    def _check_query(q: a.Query) -> list[ConstraintIssue]:
        issues: list[ConstraintIssue] = []
        node_vars: dict[str, set[str]] = {}
        rel_vars: dict[str, set[str]] = {}
        for clause in q.clauses or []:
            if isinstance(clause, a.Match):
                issues.extend(_check_inline_maps(clause.pattern))
                _bind_pattern(clause.pattern, node_vars, rel_vars)
                issues.extend(_scan_props(clause.where, node_vars, rel_vars))
            elif isinstance(clause, (a.Create, a.Merge)):
                issues.extend(_check_inline_maps(clause.pattern))
                _bind_pattern(clause.pattern, node_vars, rel_vars)
            elif isinstance(clause, a.With):
                issues.extend(_scan_props(clause, node_vars, rel_vars))
                nxt_nodes: dict[str, set[str]] = {}
                nxt_rels: dict[str, set[str]] = {}
                for expr in clause.expressions or []:
                    alias = _alias_name(expr)
                    if alias is None:
                        continue
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    if isinstance(core, a.Identifier):
                        if core.this in node_vars:
                            nxt_nodes[alias] = set(node_vars[core.this])
                        if core.this in rel_vars:
                            nxt_rels[alias] = set(rel_vars[core.this])
                node_vars, rel_vars = nxt_nodes, nxt_rels
            elif isinstance(clause, a.Return):
                issues.extend(_scan_props(clause, node_vars, rel_vars))
            elif isinstance(clause, a.Unwind):
                issues.extend(_scan_props(clause.expression, node_vars, rel_vars))
                # UNWIND list alias is not a labelled node unless prior collect —
                # leave bindings unchanged for non-alias; drop unknown.
        return issues

    root = tree.this if isinstance(tree, a.Cypher) else tree
    if isinstance(root, a.Query):
        return _check_query(root)
    if isinstance(root, a.Union):
        out: list[ConstraintIssue] = []
        for br in root.walk():
            if isinstance(br, a.Query):
                out.extend(_check_query(br))
        return out
    # Fallback: bind all patterns then scan whole tree
    node_vars: dict[str, set[str]] = {}
    rel_vars: dict[str, set[str]] = {}
    for m in tree.find_all(a.Match, a.Create, a.Merge):
        _bind_pattern(getattr(m, "pattern", None), node_vars, rel_vars)
    return _scan_props(tree, node_vars, rel_vars)


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
                        if isinstance(
                            n, (a.NodePattern, a.RelationshipPattern)
                        ) and isinstance(n.variable, a.Identifier):
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
