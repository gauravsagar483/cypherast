"""Lower dialect surface AST to neutral Cypher core for planner/executor."""

from __future__ import annotations

import typing as t

from cypherast import ast as a
from cypherast.errors import ExecuteError
from cypherast.schema import AGGREGATE_FUNCTIONS

_UNSUPPORTED = (a.Search, a.LoadCsv, a.AdminStatement, a.WhenQuery)

# Containers whose children are still part of the same surface pattern. Lowering
# descends only through these so predicates nested in expressions (EXISTS,
# comprehensions) stay with the construct that owns them. ShortestPath and
# QuantifiedPath are deliberately excluded: their predicates belong to the search
# / repetition semantics, so hoisting them into MATCH would change the query.
_PATTERN_CONTAINERS = (a.Pattern, a.PathPattern)


def lower_to_core(tree: a.AstNode, *, dialect: str | None = None) -> a.AstNode:
    """Return a core AST copy; never mutate ``tree``.

    ``dialect`` identifies the source surface for callers; lowering itself is
    structural so trees without a dialect still lower/reject surface nodes.
    """
    del dialect  # reserved for source-surface identification at call sites
    root = tree.copy()
    for node in root.walk():
        _reject_unsupported_surface(node)
    core = root.transform(_lower_node, copy=False)
    for node in core.walk():
        if isinstance(node, (a.NodePattern, a.RelationshipPattern)) and node.where is not None:
            raise ExecuteError(
                f"Unsupported inline pattern WHERE on {type(node).__name__}",
                code="CG1702",
            )
        if isinstance(node, a.Let):
            raise ExecuteError(
                "Unsupported LET outside a query clause list",
                code="CG1702",
            )
    return core


def _reject_unsupported_surface(node: a.AstNode) -> None:
    if isinstance(node, _UNSUPPORTED):
        raise ExecuteError(
            f"Unsupported core surface {type(node).__name__}",
            code="CG1702",
        )
    if not isinstance(node, a.RelationshipPattern):
        return
    if node.memgraph_quantifier == "wShortest":
        raise ExecuteError(
            "Unsupported Memgraph quantifier wShortest",
            code="CG1702",
        )
    if node.where is not None and _is_variable_length(node):
        # The binding is a relationship list, so hoisting the predicate would
        # silently reinterpret it as scalar property access on that list.
        raise ExecuteError(
            "Unsupported inline WHERE on variable-length RelationshipPattern",
            code="CG1702",
        )


def _is_variable_length(node: a.RelationshipPattern) -> bool:
    return bool(
        node.variable_length
        or node.min_hops is not None
        or node.max_hops is not None
        or node.memgraph_quantifier is not None
    )


def _lower_node(node: a.AstNode) -> a.AstNode | None:
    if isinstance(node, a.For):
        return a.Unwind(expression=node.expression, alias=node.alias)
    if isinstance(node, a.Query):
        node.clauses = _expand_let_clauses(list(node.clauses or []))
        return node
    if isinstance(node, a.Filter):
        return a.With(expressions=[a.Star()], where=_where_of(_filter_predicates(node)))
    if isinstance(node, a.Match):
        node.where = _where_of(_hoisted_predicates(node.pattern, node.where))
        return node
    if isinstance(node, a.PatternComprehension):
        node.where = _where_of(_hoisted_predicates(node.pattern, node.where))
        return node
    if isinstance(node, a.RelationshipPattern):
        if node.memgraph_quantifier == "bfs":
            node.memgraph_quantifier = None
            node.memgraph_weight_expr = None
            node.memgraph_total_weight = None
        return node
    if isinstance(node, a.CallSubquery):
        node.in_transactions = None
        node.transaction_rows = None
        return node
    if isinstance(node, (a.Return, a.With)):
        return _lower_projection(node)
    return node


def _filter_predicates(node: a.Filter) -> list[a.AstNode]:
    """Predicates of each ``FILTER`` item, keeping the item's own binding meaningful.

    ``FILTER (n WHERE …)`` scopes the predicate to ``n``, while the core form
    ``WITH * WHERE …`` filters the whole row. That is the same thing only when the
    predicate actually constrains its own binding, so anything else is rejected
    rather than silently rescoped.
    """
    preds: list[a.AstNode] = []
    for item in node.items or []:
        if item.predicate is None:
            continue
        variable = item.variable
        name = str(variable.this) if isinstance(variable, a.Identifier) else None
        if name is None or name not in _referenced_names(item.predicate):
            raise ExecuteError(
                f"Unsupported FILTER item: predicate does not reference its binding {name!r}",
                code="CG1702",
            )
        preds.append(item.predicate)
    return preds


def _referenced_names(expr: a.AstNode) -> set[str]:
    return {
        str(node.this) for node in expr.walk() if isinstance(node, a.Identifier) and node.this
    }


def _expand_let_clauses(clauses: list[a.AstNode]) -> list[a.AstNode]:
    """Expand each ``LET a = …, b = …`` into consecutive ``WITH *, item`` clauses.

    One WITH per item keeps LET's sequential scope: a later item may reference an
    earlier one, which a single WITH would evaluate in parallel instead.
    """
    out: list[a.AstNode] = []
    for clause in clauses:
        if not isinstance(clause, a.Let):
            out.append(clause)
            continue
        items = list(clause.items or [])
        if not items:
            raise ExecuteError("Unsupported LET without items", code="CG1702")
        out.extend(a.With(expressions=[a.Star(), item]) for item in items)
    return out


def _lower_projection(node: a.AstNode) -> a.AstNode:
    """Clear ``GROUP BY`` metadata only when core grouping already matches it."""
    group_by = node.group_by
    if group_by is None:
        return node
    keys = list(group_by.expressions or []) if isinstance(group_by, a.GroupBy) else [group_by]
    if not _group_by_matches_projection(node, keys):
        raise ExecuteError(
            "Unsupported GROUP BY: keys differ from the clause's non-aggregate "
            "projections, which is how core execution derives grouping",
            code="CG1702",
        )
    node.group_by = None
    return node


def _group_by_matches_projection(node: a.AstNode, keys: list[a.AstNode]) -> bool:
    """True when ``keys`` are exactly the clause's non-aggregate projections."""
    projections = list(node.expressions or [])
    if any(isinstance(expr, a.Star) for expr in projections):
        # ``WITH *`` hides the grouping keys, so equality cannot be established.
        return False
    if not any(_is_aggregate(expr) for expr in projections):
        # Without an aggregate, grouping collapses duplicate rows; core projection
        # keeps them, so the metadata is not redundant.
        return False
    grouping: list[tuple[a.AstNode, a.AstNode | None]] = []
    for expr in projections:
        if _is_aggregate(expr):
            continue
        if isinstance(expr, a.Alias):
            alias = expr.alias if isinstance(expr.alias, a.AstNode) else None
            grouping.append((expr.this, alias))
        else:
            grouping.append((expr, None))
    for key in keys:
        if not isinstance(key, a.AstNode):
            return False
        match = next(
            (
                i
                for i, (core, alias) in enumerate(grouping)
                if key == core or (alias is not None and key == alias)
            ),
            None,
        )
        if match is None:
            return False
        grouping.pop(match)
    return not grouping


def _is_aggregate(expr: a.AstNode) -> bool:
    """Top-level aggregate projection — same shape the core executor groups on."""
    node = expr.this if isinstance(expr, a.Alias) else expr
    return isinstance(node, a.FunctionCall) and str(node.name).lower() in AGGREGATE_FUNCTIONS


def _hoisted_predicates(pattern: a.AstNode | None, where: a.AstNode | None) -> list[a.AstNode]:
    """Own predicate plus inline predicates taken off ``pattern``'s own elements."""
    preds: list[a.AstNode] = []
    existing = _where_pred(where)
    if existing is not None:
        preds.append(existing)
    for element in _pattern_elements(pattern):
        inline = _where_pred(element.where)
        if inline is not None:
            preds.append(inline)
        element.where = None
    return preds


def _pattern_elements(node: a.AstNode | None) -> t.Iterator[a.AstNode]:
    """Yield node/relationship patterns owned by ``node``, skipping nested expressions."""
    if isinstance(node, (a.NodePattern, a.RelationshipPattern)):
        yield node
        return
    if not isinstance(node, _PATTERN_CONTAINERS):
        return
    for value in node.args.values():
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, a.AstNode):
                yield from _pattern_elements(item)


def _where_of(preds: list[a.AstNode]) -> a.Where | None:
    if not preds:
        return None
    result = preds[0]
    for pred in preds[1:]:
        result = a.And(this=result, expression=pred)
    return a.Where(this=result)


def _where_pred(where: a.AstNode | None) -> a.AstNode | None:
    if where is None:
        return None
    if isinstance(where, a.Where):
        pred = where.this
        return pred if isinstance(pred, a.AstNode) else None
    return where
