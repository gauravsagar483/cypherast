"""Candidate plan enumeration (scan anchors + expand direction)."""

from __future__ import annotations

from cypherglot import ast as a
from cypherglot.planner import physical_ops as ops
from cypherglot.planner.cost import estimate_cost
from cypherglot.planner.plan import Plan, _plan_match, _plan_query
from cypherglot.schema import GraphSchema


def enumerate_plans(tree: a.AstNode, schema: GraphSchema | None = None) -> list[Plan]:
    """Enumerate candidate plans: naive + alternate label-scan anchors."""
    query = tree.this if isinstance(tree, a.Cypher) else tree
    if not isinstance(query, a.Query):
        return []

    candidates: list[Plan] = []
    # Baseline
    root = _plan_query(query, schema)
    candidates.append(Plan(root=root, cost=estimate_cost(root)))

    # Alternate MATCH anchors: try each labeled node as scan start
    for clause in query.clauses:
        if not isinstance(clause, a.Match):
            continue
        anchors = _labeled_nodes(clause.pattern)
        if len(anchors) <= 1:
            continue
        for var, label, props in anchors:
            alt = _plan_match_from_anchor(clause, ops.Once(), var, label, props, schema)
            candidates.append(Plan(root=alt, cost=estimate_cost(alt)))

    # Prefer schema-aware selectivity: reorder by estimated label cardinality
    if schema is not None:
        candidates.sort(key=lambda p: _schema_adjusted_cost(p, schema))
    else:
        candidates.sort(key=lambda p: p.cost)

    # Cap
    return candidates[:8]


def _labeled_nodes(pattern: a.Pattern) -> list[tuple[str, str, list[str]]]:
    out: list[tuple[str, str, list[str]]] = []
    for path in pattern.paths:
        for el in path.elements:
            if not isinstance(el, a.NodePattern):
                continue
            if not isinstance(el.variable, a.Identifier):
                continue
            labels = el.labels.labels if isinstance(el.labels, a.LabelExpression) else []
            if not labels:
                continue
            props = (
                [k for k, _ in el.properties.entries]
                if isinstance(el.properties, a.Map)
                else []
            )
            out.append((el.variable.this, labels[0], props))
    return out


def _plan_match_from_anchor(
    clause: a.Match,
    child: ops.PhysicalOp,
    var: str,
    label: str,
    props: list[str],
    schema: GraphSchema | None,
) -> ops.PhysicalOp:
    """Build a match plan forced to scan a specific node first."""
    if props:
        scan: ops.PhysicalOp = ops.ScanAllByLabelProperties(var, label, props)
    else:
        scan = ops.ScanAllByLabel(var, label)
    scan.children = [child]
    chain = scan
    for path in clause.pattern.paths:
        elems = path.elements
        i = 1
        while i < len(elems):
            rel = elems[i]
            if isinstance(rel, a.RelationshipPattern):
                detail = ":" + "|".join(rel.types) if rel.types else ""
                if schema and rel.types:
                    detail = _orient_expand(detail, rel, schema)
                op = (
                    ops.ExpandVariable(detail)
                    if rel.variable_length
                    else ops.Expand(detail)
                )
                op.children = [chain]
                chain = op
            i += 2
    if clause.where:
        pred = clause.where.this
        detail = pred.cypher() if hasattr(pred, "cypher") else ""
        f = ops.Filter(detail)
        f.children = [chain]
        chain = f
    # Touch shared helper so plan module stays the source of truth for full queries
    _ = _plan_match
    return chain


def _orient_expand(detail: str, rel: a.RelationshipPattern, schema: GraphSchema) -> str:
    for typ in rel.types or []:
        rd = schema.rel_types.get(typ)
        if rd and rd.endpoints:
            return f"{detail} /*{rd.endpoints[0][0]}->{rd.endpoints[0][1]}*/"
    return detail


def _schema_adjusted_cost(plan: Plan, schema: GraphSchema) -> float:
    cost = plan.cost
    # Prefer scans on low-cardinality labels when stats present
    for name, card in schema.stats.items():
        label = name.split(":", 1)[1] if name.startswith("label:") else ""
        if label and label in (plan.root.detail or ""):
            cost *= max(0.1, min(1.0, card / 1000.0))
    return cost
