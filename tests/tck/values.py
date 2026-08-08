"""Format executor values in openCypher TCK notation for comparison."""

from __future__ import annotations

import math
import typing as t

from cypherast.executor.graph import Node, Relationship

if t.TYPE_CHECKING:
    from cypherast.executor.engine import Result


def format_value(value: t.Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value) and value > 0:
            return "Inf"
        if math.isinf(value):
            return "-Inf"
        text = repr(value)
        if "e" in text or "E" in text:
            return text
        return format(value, "g")
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if isinstance(value, Node):
        return format_node(value)
    if isinstance(value, Relationship):
        return format_relationship(value)
    if isinstance(value, list):
        flat = _flatten_path_items(value)
        if flat and isinstance(flat[0], Node) and all(
            isinstance(x, (Node, Relationship)) for x in flat
        ):
            return format_path(flat)
        if value and all(isinstance(x, Relationship) for x in value):
            inner = ", ".join(format_relationship(x) for x in value)
            return f"[{inner}]"
        if value and all(isinstance(x, list) for x in value):
            inner = ", ".join(format_value(v) for v in value)
            return f"[{inner}]"
        inner = ", ".join(format_value(v) for v in value)
        return f"[{inner}]"
    if isinstance(value, dict):
        items = ", ".join(f"{k}: {format_value(v)}" for k, v in sorted(value.items()))
        return f"{{{items}}}"
    return str(value)


def format_node(node: Node) -> str:
    labels = "".join(f":{label}" for label in sorted(node.labels))
    if node.props:
        props = ", ".join(f"{k}: {format_value(v)}" for k, v in sorted(node.props.items()))
        if labels:
            return f"({labels} {{{props}}})"
        return f"({{{props}}})"
    if labels:
        return f"({labels})"
    return "()"


def format_relationship(rel: Relationship) -> str:
    if rel.props:
        props = ", ".join(f"{k}: {format_value(v)}" for k, v in sorted(rel.props.items()))
        return f"[:{rel.type} {{{props}}}]"
    return f"[:{rel.type}]"


def _flatten_path_items(items: list[t.Any]) -> list[t.Any]:
    """Flatten ``[node, [rel, rel], node]`` path accumulators from the executor."""
    if not items:
        return items
    if not isinstance(items[0], Node):
        return items
    flat: list[t.Any] = []
    for item in items:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    if flat and all(isinstance(x, (Node, Relationship)) for x in flat):
        return flat
    return items


def format_path(items: list[t.Any]) -> str:
    if not items:
        return "<>"
    if len(items) == 1 and isinstance(items[0], Node):
        return f"<{format_node(items[0])}>"

    parts: list[str] = ["<"]
    prev: Node | None = None
    i = 0
    if isinstance(items[0], Node):
        parts.append(format_node(items[0]))
        prev = items[0]
        i = 1

    while i < len(items):
        rel = items[i]
        if not isinstance(rel, Relationship):
            break
        end = items[i + 1] if i + 1 < len(items) else None
        if prev is not None and end is not None and isinstance(end, Node):
            if rel.start == prev.id and rel.end == end.id:
                parts.append(f"-{format_relationship(rel)}->")
            elif rel.end == prev.id and rel.start == end.id:
                parts.append(f"<-{format_relationship(rel)}-")
            else:
                parts.append(f"-{format_relationship(rel)}->")
            parts.append(format_node(end))
            prev = end
            i += 2
        else:
            parts.append(format_relationship(rel))
            i += 1
    parts.append(">")
    return "".join(parts)


def result_rows(result: Result, columns: list[str]) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for row in result:
        rows.append(tuple(format_value(row.get(col)) for col in columns))
    return rows
