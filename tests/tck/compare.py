"""Normalize TCK table cells for order-insensitive comparison."""

from __future__ import annotations

import re


def normalize_cell(cell: str, *, list_order_insensitive: bool = False) -> str:
    text = cell.strip()
    if list_order_insensitive and text.startswith("[") and text.endswith("]"):
        return _normalize_list_cell(text)
    return _normalize_node_labels(text)


def normalize_row(row: tuple[str, ...], *, list_order_insensitive: bool = False) -> tuple[str, ...]:
    return tuple(normalize_cell(c, list_order_insensitive=list_order_insensitive) for c in row)


def rows_equal(
    expected: list[tuple[str, ...]],
    actual: list[tuple[str, ...]],
    *,
    any_order: bool,
    list_order_insensitive: bool = False,
) -> bool:
    def norm(rows: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
        return [normalize_row(r, list_order_insensitive=list_order_insensitive) for r in rows]

    exp = norm(expected)
    act = norm(actual)
    if any_order:
        return sorted(exp) == sorted(act)
    return exp == act


def _normalize_list_cell(cell: str) -> str:
    inner = cell[1:-1].strip()
    if not inner:
        return "[]"
    parts = [_normalize_list_cell(p) if p.startswith("[") else _normalize_node_labels(p) for p in _split_top_level(inner)]
    return "[" + ", ".join(sorted(parts)) + "]"


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "[{<(":
            depth += 1
        elif ch in "]})>":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return parts


def _normalize_node_labels(cell: str) -> str:
    def sort_node(match: re.Match[str]) -> str:
        content = match.group(1)
        brace = content.find("{")
        label_part = content[:brace] if brace >= 0 else content
        rest = content[brace:] if brace >= 0 else ""
        labels = [part for part in label_part.split(":") if part]
        if not labels:
            return f"({rest})" if rest else "()"
        ordered = ":" + ":".join(sorted(labels, key=str.lower))
        return f"({ordered}{rest})"

    return re.sub(r"\(([^<>][^)]*)\)", sort_node, cell)
