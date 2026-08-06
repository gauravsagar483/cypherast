"""Plan construction: naive + cost-based."""

from __future__ import annotations

from dataclasses import dataclass

from cypherglot import ast as a
from cypherglot.planner import physical_ops as ops
from cypherglot.planner.cost import estimate_cost
from cypherglot.schema import GraphSchema


@dataclass
class Plan:
    root: ops.PhysicalOp
    cost: float = 0.0


def build_naive_plan(tree: a.AstNode) -> Plan:
    query = tree.this if isinstance(tree, a.Cypher) else tree
    root = ops.Once()
    if isinstance(query, a.Query):
        root = _plan_query(query, schema=None)
    return Plan(root=root, cost=estimate_cost(root))


def build_cost_plan(tree: a.AstNode, schema: object | None = None) -> Plan:
    from cypherglot.planner.enumeration import enumerate_plans

    gs = schema if isinstance(schema, GraphSchema) else None
    candidates = enumerate_plans(tree, schema=gs)
    if not candidates:
        return build_naive_plan(tree)
    best = min(candidates, key=lambda p: p.cost)
    return best


def _plan_query(query: a.Query, schema: GraphSchema | None) -> ops.PhysicalOp:
    chain = ops.Once()
    produce_symbols: list[str] = []
    for clause in query.clauses:
        if isinstance(clause, a.Match):
            chain = _plan_match(clause, chain, schema)
        elif isinstance(clause, a.With):
            chain = _plan_projection(clause, chain)
        elif isinstance(clause, a.Unwind):
            detail = clause.alias.this if isinstance(clause.alias, a.Identifier) else ""
            chain = ops.PhysicalOp("Unwind", detail, children=[chain])
        elif isinstance(clause, a.Create):
            chain = ops.PhysicalOp("CreateNode", children=[chain])
        elif isinstance(clause, a.Merge):
            chain = ops.PhysicalOp("Merge", children=[chain])
        elif isinstance(clause, a.Set):
            chain = ops.PhysicalOp("SetProperty", children=[chain])
        elif isinstance(clause, a.Delete):
            chain = ops.PhysicalOp("Delete", children=[chain])
        elif isinstance(clause, a.Return):
            produce_symbols = [_sym(e) for e in (clause.expressions or [])]
            inner = chain
            if any(_is_agg(e) for e in (clause.expressions or [])):
                inner = ops.Aggregate(children=[inner])
            if clause.distinct:
                inner = ops.PhysicalOp("Distinct", children=[inner])
            if clause.order:
                inner = ops.OrderBy(children=[inner])
            if clause.skip:
                inner = ops.SkipOp(children=[inner])
            if clause.limit:
                inner = ops.LimitOp(children=[inner])
            chain = ops.Produce(produce_symbols)
            chain.children = [inner]
        else:
            chain = ops.PhysicalOp(type(clause).__name__, children=[chain])
    if chain.name != "Produce":
        er = ops.EmptyResult()
        er.children = [chain]
        return er
    return chain


def _plan_match(
    clause: a.Match, child: ops.PhysicalOp, schema: GraphSchema | None
) -> ops.PhysicalOp:
    # Pick first node pattern as scan source
    node_pat = None
    for path in clause.pattern.paths:
        for el in path.elements:
            if isinstance(el, a.NodePattern):
                node_pat = el
                break
        if node_pat:
            break
    scan: ops.PhysicalOp = child
    if node_pat:
        var = node_pat.variable.this if isinstance(node_pat.variable, a.Identifier) else "anon"
        labels = node_pat.labels.labels if isinstance(node_pat.labels, a.LabelExpression) else []
        props = []
        if isinstance(node_pat.properties, a.Map):
            props = [k for k, _ in node_pat.properties.entries]
        if labels and props:
            scan = ops.ScanAllByLabelProperties(var, labels[0], props)
        elif labels:
            scan = ops.ScanAllByLabel(var, labels[0])
        else:
            scan = ops.ScanAll(var)
        scan.children = [child]
    # Expands for subsequent relationships
    chain = scan
    for path in clause.pattern.paths:
        elems = path.elements
        i = 1
        while i < len(elems):
            rel = elems[i]
            if isinstance(rel, a.RelationshipPattern):
                detail = ""
                if rel.types:
                    detail = ":" + "|".join(rel.types)
                op = ops.ExpandVariable(detail) if rel.variable_length else ops.Expand(detail)
                op.children = [chain]
                chain = op
            i += 2
    if clause.where:
        f = ops.Filter(
            clause.where.this.cypher() if hasattr(clause.where.this, "cypher") else ""
        )
        f.children = [chain]
        chain = f
    return chain


def _plan_projection(clause: a.With, child: ops.PhysicalOp) -> ops.PhysicalOp:
    chain = child
    if clause.where:
        f = ops.Filter(children=[chain])
        chain = f
    if clause.order:
        chain = ops.OrderBy(children=[chain])
    return chain


def _sym(expr: a.AstNode) -> str:
    if isinstance(expr, a.Alias) and isinstance(expr.alias, a.Identifier):
        return str(expr.alias.this)
    if isinstance(expr, a.Identifier):
        return str(expr.this)
    if isinstance(expr, a.Property):
        return str(expr.name)
    if isinstance(expr, a.Star):
        return "*"
    return type(expr).__name__


def _is_agg(expr: a.AstNode) -> bool:
    node = expr.this if isinstance(expr, a.Alias) else expr
    return isinstance(node, a.FunctionCall) and node.name.lower() in {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "collect",
    }
