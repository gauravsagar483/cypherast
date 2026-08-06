"""Cost estimation for physical operators."""

from __future__ import annotations

from cypherast.planner.physical_ops import PhysicalOp

# Coefficient table (relative units)
COEFF: dict[str, float] = {
    "Once": 0.0,
    "ScanAll": 100.0,
    "ScanAllByLabel": 20.0,
    "ScanAllByLabelProperties": 5.0,
    "ScanAllById": 1.0,
    "Expand": 10.0,
    "ExpandVariable": 50.0,
    "Filter": 2.0,
    "Aggregate": 15.0,
    "OrderBy": 20.0,
    "Distinct": 10.0,
    "Unwind": 5.0,
    "Produce": 1.0,
    "CreateNode": 5.0,
    "CreateExpand": 8.0,
    "Merge": 12.0,
    "Delete": 5.0,
    "SetProperty": 2.0,
    "EmptyResult": 0.0,
    "Skip": 1.0,
    "Limit": 1.0,
}


def estimate_cost(op: PhysicalOp) -> float:
    total = COEFF.get(op.name, 5.0) + sum(estimate_cost(c) for c in op.children)
    op.cost = total
    return total
