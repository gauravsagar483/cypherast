"""Literal-stripped plan cache."""

from __future__ import annotations

from cypherglot.planner.plan import Plan


class PlanCache:
    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._store: dict[str, Plan] = {}

    def get(self, key: str) -> Plan | None:
        return self._store.get(key)

    def put(self, key: str, plan: Plan) -> None:
        if len(self._store) >= self.max_size:
            # drop arbitrary first key
            self._store.pop(next(iter(self._store)))
        self._store[key] = plan

    def clear(self) -> None:
        self._store.clear()


def cache_key(cypher: str) -> str:
    """Normalize by replacing string/number literals with placeholders (rough)."""
    import re

    s = re.sub(r"'([^'\\]|\\.)*'", "'?'", cypher)
    s = re.sub(r"\b\d+(\.\d+)?\b", "0", s)
    return " ".join(s.split())
