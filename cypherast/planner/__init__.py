"""Query planner: naive + cost-based."""

from cypherast import ast as a
from cypherast.planner.physical_ops import format_plan
from cypherast.planner.plan import Plan, build_cost_plan, build_naive_plan


def explain(tree: a.AstNode, schema: object | None = None) -> str:
    plan = build_cost_plan(tree, schema=schema) if schema else build_naive_plan(tree)
    return format_plan(plan)


def profile(
    tree: a.AstNode,
    schema: object | None = None,
    graph: object | None = None,
) -> str:
    from cypherast.executor import execute

    plan = build_cost_plan(tree, schema=schema) if schema else build_naive_plan(tree)
    result = execute(tree, graph=graph)  # type: ignore[arg-type]
    text = format_plan(plan)
    text += f"\n\nRows: {len(result)}"
    return text


def plan_query(tree: a.AstNode, schema: object | None = None, cost: bool = True) -> Plan:
    if cost:
        return build_cost_plan(tree, schema=schema)
    return build_naive_plan(tree)
