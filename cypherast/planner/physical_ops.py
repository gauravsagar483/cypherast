"""Physical plan operators (Memgraph/Neo4j-inspired)."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field


@dataclass
class PhysicalOp:
    name: str
    detail: str = ""
    children: list[PhysicalOp] = field(default_factory=list)
    cost: float = 0.0
    rows_estimate: float = 0.0

    def label(self) -> str:
        if self.detail:
            return f"{self.name} {self.detail}"
        return self.name


def Once(children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Once")
    if children:
        op.children = children
    return op


def Produce(symbols: list[str], children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Produce", "{" + ", ".join(symbols) + "}")
    if children:
        op.children = children
    return op


def ScanAll(var: str, children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("ScanAll", f"({var})")
    if children:
        op.children = children
    return op


def ScanAllByLabel(
    var: str, label: str, children: list[PhysicalOp] | None = None
) -> PhysicalOp:
    op = PhysicalOp("ScanAllByLabel", f"({var} :{label})")
    if children:
        op.children = children
    return op


def ScanAllByLabelProperties(
    var: str, label: str, props: list[str], children: list[PhysicalOp] | None = None
) -> PhysicalOp:
    prop_s = ", ".join(props)
    op = PhysicalOp("ScanAllByLabelProperties", f"({var} :{label} {{{prop_s}}})")
    if children:
        op.children = children
    return op


def Filter(detail: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Filter", detail)
    if children:
        op.children = children
    return op


def Expand(detail: str, children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Expand", detail)
    if children:
        op.children = children
    return op


def ExpandVariable(detail: str, children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("ExpandVariable", detail)
    if children:
        op.children = children
    return op


def CreateNode(detail: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("CreateNode", detail)
    if children:
        op.children = children
    return op


def CreateExpand(detail: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("CreateExpand", detail)
    if children:
        op.children = children
    return op


def Aggregate(detail: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Aggregate", detail)
    if children:
        op.children = children
    return op


def OrderBy(detail: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("OrderBy", detail)
    if children:
        op.children = children
    return op


def SkipOp(n: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Skip", n)
    if children:
        op.children = children
    return op


def LimitOp(n: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Limit", n)
    if children:
        op.children = children
    return op


def DistinctOp(children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Distinct")
    if children:
        op.children = children
    return op


def UnwindOp(detail: str = "", children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("Unwind", detail)
    if children:
        op.children = children
    return op


def EmptyResult(children: list[PhysicalOp] | None = None) -> PhysicalOp:
    op = PhysicalOp("EmptyResult")
    if children:
        op.children = children
    return op

def format_plan(plan: t.Any) -> str:
    """Memgraph-style bottom-up textual plan."""
    lines: list[str] = ["+---------------------------+", "| QUERY PLAN                |", "+---------------------------+"]
    ops = _flatten(plan.root)
    for op in reversed(ops):
        cost = f"  cost={op.cost:.1f}" if op.cost else ""
        lines.append(f"|  * {op.label()}{cost}")
    lines.append("+---------------------------+")
    return "\n".join(lines)


def _flatten(op: PhysicalOp, acc: list[PhysicalOp] | None = None) -> list[PhysicalOp]:
    acc = acc if acc is not None else []
    for c in op.children:
        _flatten(c, acc)
    acc.append(op)
    return acc
