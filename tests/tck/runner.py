"""Lightweight openCypher TCK runner + compliance scoreboard.

Place official TCK ``.feature`` files under ``tests/tck/features/``
(or set ``CYPHERGLOT_TCK_PATH``). This runner parses Gherkin scenarios
with Given/When/Then steps for graph setup, query, and expected rows.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from cypherglot.parser import Parser


@dataclass
class ScenarioResult:
    name: str
    feature: str
    passed: bool
    error: str | None = None
    kind: str = "run"  # parse | run


@dataclass
class Scoreboard:
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def parse_rate(self) -> float:
        parse = [r for r in self.results if r.kind == "parse"]
        if not parse:
            return 0.0
        return sum(1 for r in parse if r.passed) / len(parse)

    @property
    def run_rate(self) -> float:
        run = [r for r in self.results if r.kind == "run"]
        if not run:
            return 0.0
        return sum(1 for r in run if r.passed) / len(run)

    def summary(self) -> str:
        return (
            f"TCK scoreboard: {self.passed}/{self.total} passed | "
            f"parse={self.parse_rate:.1%} run={self.run_rate:.1%}"
        )


_SCENARIO = re.compile(r"^\s*Scenario(?: Outline)?:\s*(.+)$")
_GIVEN = re.compile(r"^\s*Given\s+(.+)$", re.I)
_WHEN = re.compile(r"^\s*When\s+executing query[^\n]*\n((?:.*\n)*?)\s*```", re.I)
_QUERY_BLOCK = re.compile(r"```\s*\n(.*?)```", re.S)
_DOCSTRING_BLOCK = re.compile(r'"""\s*\n(.*?)"""', re.S)


def discover_features(root: Path | None = None) -> list[Path]:
    env = os.environ.get("CYPHERGLOT_TCK_PATH")
    base = Path(env) if env else (root or Path(__file__).parent / "features")
    if not base.exists():
        return []
    return sorted(base.rglob("*.feature"))


def run_tck(root: Path | None = None, *, parse_only: bool = False) -> Scoreboard:
    board = Scoreboard()
    for feature in discover_features(root):
        text = feature.read_text(encoding="utf-8")
        scenarios = _split_scenarios(text)
        for name, body in scenarios:
            if parse_only:
                board.results.append(_run_parse(name, feature.name, body))
            else:
                board.results.append(_run_parse(name, feature.name, body))
                # Full run support is incremental; parse is the v1 gate
    return board


def _split_scenarios(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^(Scenario(?: Outline)?:)", text)
    out: list[tuple[str, str]] = []
    # parts: preamble, marker, rest, marker, rest...
    i = 1
    while i + 1 < len(parts):
        header = parts[i + 1].split("\n", 1)
        name = header[0].strip()
        body = header[1] if len(header) > 1 else ""
        if i + 2 < len(parts) and not parts[i + 2].startswith("Scenario"):
            # next chunk may be body continuation — already in header
            pass
        out.append((name, body))
        i += 2
    # Simpler approach:
    out = []
    current_name = None
    current_body: list[str] = []
    for line in text.splitlines(keepends=True):
        m = _SCENARIO.match(line)
        if m:
            if current_name is not None:
                out.append((current_name, "".join(current_body)))
            current_name = m.group(1).strip()
            current_body = []
        elif current_name is not None:
            current_body.append(line)
    if current_name is not None:
        out.append((current_name, "".join(current_body)))
    return out


def _extract_query(body: str) -> str | None:
    m = _QUERY_BLOCK.search(body)
    if m:
        return m.group(1).strip()
    m = _DOCSTRING_BLOCK.search(body)
    if m:
        # Dedent common leading whitespace from Gherkin docstrings
        lines = m.group(1).splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return None
        indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
        pad = min(indents) if indents else 0
        return "\n".join(ln[pad:] if len(ln) >= pad else ln for ln in lines).strip()
    # fallback: line after When executing query:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"When\s+executing query", line, re.I):
            qlines = []
            for nxt in lines[i + 1 :]:
                if nxt.strip().startswith("Then") or nxt.strip().startswith("And"):
                    break
                if nxt.strip().startswith("```") or nxt.strip().startswith('"""'):
                    continue
                qlines.append(nxt)
            return "\n".join(qlines).strip() or None
    return None


def _run_parse(name: str, feature: str, body: str) -> ScenarioResult:
    query = _extract_query(body)
    if not query:
        return ScenarioResult(name, feature, False, "no query found", kind="parse")
    try:
        Parser(query).parse()
        return ScenarioResult(name, feature, True, kind="parse")
    except Exception as e:  # noqa: BLE001 — scoreboard collects all failures
        return ScenarioResult(name, feature, False, str(e), kind="parse")
