"""Built-in procedure stubs for in-memory execution."""

from __future__ import annotations

import typing as t

from cypherast.executor.graph import Graph

ProcedureFn = t.Callable[[Graph, list[t.Any]], list[dict[str, t.Any]]]


def _db_labels(graph: Graph, _args: list[t.Any]) -> list[dict[str, t.Any]]:
    labels: set[str] = set()
    for node in graph.all_nodes():
        labels.update(node.labels)
    return [{"label": label} for label in sorted(labels)]


PROCEDURES: dict[str, ProcedureFn] = {
    "db.labels": _db_labels,
}


def run_procedure(name: str, graph: Graph, args: list[t.Any]) -> list[dict[str, t.Any]]:
    key = name.lower()
    fn = PROCEDURES.get(key)
    if fn is None:
        return [{"ok": True}]
    return fn(graph, args)
