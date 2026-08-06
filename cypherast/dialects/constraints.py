"""Generic dialect constraint rewrites + validators (engine-agnostic helpers).

Callers pass a ``DialectCapabilities`` snapshot. Label names come from
``GraphSchema`` only — never hard-coded domain vocabulary here.
"""

from __future__ import annotations

from dataclasses import dataclass

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.errors import ValidationError
from cypherast.schema import GraphSchema


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
    if caps.max_var_length_hops is not None or not caps.allow_unbounded_var_length:
        node = bound_variable_length(
            node,
            max_hops=caps.max_var_length_hops or 5,
            allow_unbounded=caps.allow_unbounded_var_length,
        )
    if not caps.allow_cartesian_match_paths:
        node = split_multi_path_match(node)
    if caps.require_limit_on_row_return:
        node = ensure_row_limit(node, limit=caps.default_row_limit)
    if not caps.allow_distinct_with_aggregate:
        node = drop_distinct_beside_aggregate(node)
    if caps.max_collect_distinct_per_clause is not None:
        node = cap_collect_distinct(node, max_n=caps.max_collect_distinct_per_clause)
    return node


def validate_capabilities(
    tree: a.AstNode, caps: DialectCapabilities
) -> list[ConstraintIssue]:
    """Report remaining violations (after or instead of rewrite)."""
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
    if not caps.allow_exists_function:
        issues.extend(_exists_function_calls(tree))
    if caps.require_limit_on_row_return:
        issues.extend(_missing_row_limit(tree))
    if not caps.allow_distinct_with_aggregate:
        issues.extend(_distinct_with_aggregate(tree))
    if caps.max_collect_distinct_per_clause is not None:
        issues.extend(
            _too_many_collect_distinct(tree, caps.max_collect_distinct_per_clause)
        )
    if not caps.pattern_predicate_introduces_bindings:
        issues.extend(_pattern_predicate_bindings(tree))
    return issues


def raise_if_invalid(tree: a.AstNode, caps: DialectCapabilities) -> None:
    issues = validate_capabilities(tree, caps)
    if not issues:
        return
    first = issues[0]
    raise ValidationError(
        first.message,
        code=first.code
        if first.code
        in {"CG1201", "CG1202", "CG1203", "CG1401", "CG1402"}
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


def ensure_row_limit(tree: a.AstNode, *, limit: int) -> a.AstNode:
    def _is_agg_expr(expr: a.AstNode) -> bool:
        node = expr.this if isinstance(expr, a.Alias) else expr
        return isinstance(node, a.FunctionCall) and str(node.name).lower() in {
            "count",
            "sum",
            "avg",
            "min",
            "max",
            "collect",
        }

    def _fix(node: a.AstNode) -> a.AstNode | None:
        if not isinstance(node, a.Return) or node.limit is not None:
            return node
        exprs = node.expressions or []
        if exprs and all(_is_agg_expr(e) for e in exprs):
            return node  # pure aggregates may omit LIMIT
        node.limit = a.Limit(this=a.Integer(this=limit))
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
    """Fill missing MATCH node labels from ``GraphSchema`` rel endpoints.

    Uses adjacent relationship types (+ direction) to pick start/end labels.
    When several labels remain possible, emits a label OR expression
    (``:a|b``). Also names formerly anonymous nodes once labelled so qualify
    skipping ``()`` does not leave bare anons after optimize.
    """
    gs = schema if isinstance(schema, GraphSchema) else None
    if gs is None or not gs.rel_types:
        return tree

    counter = {"n": 0}

    def _name() -> str:
        counter["n"] += 1
        return f"_n_{counter['n']}"

    def _existing_labels(n: a.NodePattern) -> set[str]:
        if not isinstance(n.labels, a.LabelExpression):
            return set()
        if n.labels.expression:
            return {str(n.labels.expression)}
        if n.labels.labels:
            return {str(x) for x in n.labels.labels}
        return set()

    def _apply_labels(n: a.NodePattern, cands: set[str]) -> None:
        if not cands or _existing_labels(n):
            return
        if len(cands) == 1:
            n.labels = a.LabelExpression(labels=[next(iter(cands))])
        else:
            n.labels = a.LabelExpression(
                labels=[],
                expression="|".join(sorted(cands)),
            )
        if n.variable is None:
            n.variable = a.Identifier(this=_name())

    def _rel_def(tname: str):
        rd = gs.rel_types.get(tname) or gs.rel_types.get(tname.lower())
        if rd is not None:
            return rd
        for k, v in gs.rel_types.items():
            if k.lower() == tname.lower():
                return v
        return None

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

    def _infer_path(path: a.PathPattern) -> None:
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
            left_labs = _existing_labels(left)
            right_labs = _existing_labels(right)

            if left_labs:
                narrowed_ends: set[str] = set()
                for tname in types:
                    rd = _rel_def(tname)
                    if rd is None:
                        continue
                    for s, e in rd.endpoints:
                        if s in left_labs:
                            narrowed_ends.add(e)
                if narrowed_ends:
                    ends = narrowed_ends
            if right_labs:
                narrowed_starts: set[str] = set()
                for tname in types:
                    rd = _rel_def(tname)
                    if rd is None:
                        continue
                    for s, e in rd.endpoints:
                        if e in right_labs:
                            narrowed_starts.add(s)
                if narrowed_starts:
                    starts = narrowed_starts

            d = rel.direction
            if d is a.Direction.OUTGOING:
                _apply_labels(left, starts)
                _apply_labels(right, ends)
            elif d is a.Direction.INCOMING:
                _apply_labels(left, ends)
                _apply_labels(right, starts)
            else:
                if starts == ends and len(starts) == 1:
                    _apply_labels(left, starts)
                    _apply_labels(right, ends)
                elif left_labs and not right_labs:
                    _apply_labels(right, ends if ends else starts)
                elif right_labs and not left_labs:
                    _apply_labels(left, starts if starts else ends)
                elif not left_labs and not right_labs and len(starts | ends) == 1:
                    one = starts | ends
                    _apply_labels(left, one)
                    _apply_labels(right, one)
            i += 2

    for match in tree.find_all(a.Match):
        assert isinstance(match, a.Match)
        if not isinstance(match.pattern, a.Pattern):
            continue
        for path in match.pattern.paths or []:
            if isinstance(path, a.PathPattern):
                _infer_path(path)
    return tree


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
    Anonymous ``()`` and new unlabelled ``(x)`` always fail.
    """
    issues: list[ConstraintIssue] = []
    labelled: set[str] = set()

    def _label_names(n: a.NodePattern) -> list[str]:
        if isinstance(n.labels, a.LabelExpression):
            if n.labels.expression:
                return [str(n.labels.expression)]
            return list(n.labels.labels or [])
        return []

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
        nonlocal labelled
        nxt: set[str] = set()
        for expr in clause.expressions or []:
            if isinstance(expr, a.Alias):
                src = expr.this.this if isinstance(expr.this, a.Identifier) else None
                alias = (
                    expr.alias.this
                    if isinstance(expr.alias, a.Identifier)
                    else expr.alias
                    if isinstance(expr.alias, str)
                    else None
                )
                if src in labelled and alias:
                    nxt.add(alias)
            elif isinstance(expr, a.Identifier) and expr.this in labelled:
                nxt.add(expr.this)
        labelled = nxt

    root: a.AstNode | None = tree
    if isinstance(tree, a.Cypher) and isinstance(tree.this, a.Query):
        root = tree.this
    if isinstance(root, a.Query) and root.clauses:
        for clause in root.clauses:
            if isinstance(clause, a.Match):
                _check_match(clause)
            elif isinstance(clause, a.With):
                _apply_with(clause)
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


def _missing_row_limit(tree: a.AstNode) -> list[ConstraintIssue]:
    for n in tree.find_all(a.Return):
        assert isinstance(n, a.Return)
        if n.limit is not None:
            continue
        exprs = n.expressions or []

        def _agg(e: a.AstNode) -> bool:
            c = e.this if isinstance(e, a.Alias) else e
            return isinstance(c, a.FunctionCall) and str(c.name).lower() in {
                "count",
                "sum",
                "avg",
                "min",
                "max",
                "collect",
            }

        if exprs and all(_agg(e) for e in exprs):
            continue
        return [
            ConstraintIssue(
                "CG1401",
                "Row-returning queries must include LIMIT",
                hint="Add LIMIT N (pure aggregates may omit)",
            )
        ]
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


def _pattern_predicate_bindings(tree: a.AstNode) -> list[ConstraintIssue]:
    for pred in tree.find_all(a.PatternPredicate):
        assert isinstance(pred, a.PatternPredicate)
        for n in pred.walk():
            if isinstance(n, (a.NodePattern, a.RelationshipPattern)) and isinstance(
                n.variable, a.Identifier
            ):
                name = str(n.variable.this)
                # Flag generated _n_ / _r_ bindings inside predicates
                if name.startswith("_"):
                    return [
                        ConstraintIssue(
                            "CG1401",
                            "Pattern predicates must not introduce new variables",
                            hint="Keep anonymous (:Label) / -[:TYPE]- inside WHERE patterns",
                        )
                    ]
    return []
