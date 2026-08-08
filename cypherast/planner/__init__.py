"""Query planner: naive + cost-based.

Planning always lowers to neutral Cypher core first, so the guarantee is
structural rather than dependent on the caller naming a source ``dialect=``.
``dialect=`` only identifies that source surface; lowering core AST again is
idempotent.
"""

from __future__ import annotations

from cypherast import ast as a
from cypherast.executor.graph import Graph
from cypherast.planner.physical_ops import format_plan
from cypherast.planner.plan import Plan, build_cost_plan, build_naive_plan


def explain(
    tree: a.AstNode,
    schema: object | None = None,
    *,
    dialect: str | None = None,
) -> str:
    """Return a textual plan over neutral core AST."""
    tree = _core(tree, dialect=dialect)
    plan = build_cost_plan(tree, schema=schema) if schema else build_naive_plan(tree)
    return format_plan(plan)


def profile(
    tree: a.AstNode,
    schema: object | None = None,
    graph: Graph | None = None,
    *,
    dialect: str | None = None,
) -> str:
    """Profile row counts over neutral core AST."""
    from cypherast.executor import execute

    tree = _core(tree, dialect=dialect)
    plan = build_cost_plan(tree, schema=schema) if schema else build_naive_plan(tree)
    # Tree is neutral core — do not re-identify a source dialect on execute.
    result = execute(tree, graph=graph, dialect=None)
    text = format_plan(plan)
    text += f"\n\nRows: {len(result)}"
    return text


def plan_query(
    tree: a.AstNode,
    schema: object | None = None,
    cost: bool = True,
    *,
    dialect: str | None = None,
) -> Plan:
    """Build a plan over neutral core AST."""
    tree = _core(tree, dialect=dialect)
    if cost:
        return build_cost_plan(tree, schema=schema)
    return build_naive_plan(tree)


def _core(tree: a.AstNode, *, dialect: str | None) -> a.AstNode:
    from cypherast.dialects.lower import lower_to_core

    return lower_to_core(tree, dialect=dialect)
