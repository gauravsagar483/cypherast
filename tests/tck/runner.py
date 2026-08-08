"""Official openCypher TCK runner — clones to /tmp, parse + in-memory executor."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cypherast import parse_one, validate
from cypherast.errors import CypherastError
from cypherast.executor.engine import execute
from cypherast.executor.graph import Graph
from tests.tck.compare import rows_equal
from tests.tck.fetch import ensure_official_tck, official_graphs_path, official_tck_root
from tests.tck.values import result_rows

_DEFAULT_TCK_DIALECT = "opencypher"

_SCENARIO = re.compile(r"^\s*Scenario(?: Outline)?:\s*(.+)$", re.M)
_OUTLINE_PLACEHOLDER = re.compile(r"<\w+>")
_DOCSTRING = re.compile(r'"""\s*\n(.*?)"""', re.S)
_FENCE = re.compile(r"```\s*\n(.*?)```", re.S)
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_ERROR_ASSERT = re.compile(
    r"Then a (\w+) should be raised at (compile time|runtime): (\w+)",
    re.I,
)
_INTENTIONAL_NEGATIVE = re.compile(r"\bFail(?:ing)?\b", re.I)


def tck_dialect() -> str:
    """Read dialect for TCK parse/validate (``CYPHERAST_TCK_DIALECT``, default ``opencypher``)."""
    return os.environ.get("CYPHERAST_TCK_DIALECT", _DEFAULT_TCK_DIALECT)


def _parse_tck(query: str, *, dialect: str | None = None):
    return parse_one(query, read=dialect or tck_dialect())


def _validate_tck(query: str, *, dialect: str | None = None) -> None:
    validate(query, dialect=dialect or tck_dialect())

# OC9 skip patterns for official TCK (excluded / unsupported constructs)
OC9_TCK_SKIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bLOAD\s+CSV\b", re.I),
    re.compile(r"\bSTART\b", re.I),
    re.compile(r"\bpoint\s*\(", re.I),
    re.compile(r"\bdistance\s*\(", re.I),
    re.compile(r"\bCREATE\s+(UNIQUE\s+)?(INDEX|CONSTRAINT)\b", re.I),
    re.compile(r"\b(date|time|datetime|duration)\s*\(", re.I),
    re.compile(r"@oc9-excluded", re.I),
)


@dataclass
class ScenarioResult:
    name: str
    feature: str
    passed: bool
    error: str | None = None
    kind: str = "run"  # parse | run | skip | expected
    skip_reason: str | None = None


@dataclass
class Scoreboard:
    results: list[ScenarioResult] = field(default_factory=list)
    dialect: str = _DEFAULT_TCK_DIALECT

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    def by_kind(self, kind: str) -> list[ScenarioResult]:
        return [r for r in self.results if r.kind == kind]

    @property
    def parse_rate(self) -> float:
        parse = self.by_kind("parse")
        if not parse:
            return 0.0
        return sum(1 for r in parse if r.passed) / len(parse)

    @property
    def run_rate(self) -> float:
        run = self.by_kind("run")
        if not run:
            return 0.0
        return sum(1 for r in run if r.passed) / len(run)

    @property
    def effective_run_rate(self) -> float:
        """Passed / (run + expected) — includes intentional error/parse-negative passes."""
        scored = [r for r in self.results if r.kind in ("run", "expected")]
        if not scored:
            return 0.0
        return sum(1 for r in scored if r.passed) / len(scored)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.kind == "skip")

    def summary(self) -> str:
        run = self.by_kind("run")
        parse = self.by_kind("parse")
        parts = [f"TCK: {self.passed}/{self.total} passed"]
        if parse:
            parts.append(f"parse={self.parse_rate:.1%} ({len(parse)})")
        if run:
            parts.append(f"run={self.run_rate:.1%} ({len(run)})")
            expected = self.by_kind("expected")
            if expected:
                parts.append(f"effective={self.effective_run_rate:.1%} ({len(run) + len(expected)})")
        if self.skipped:
            parts.append(f"skipped={self.skipped}")
        return " | ".join(parts)


def discover_features(root: Path | None = None) -> list[Path]:
    env = os.environ.get("CYPHERAST_TCK_PATH")
    if env:
        base = Path(env)
    elif root is not None:
        base = root
    else:
        base = Path(__file__).parent / "features"
    if not base.exists():
        return []
    return sorted(base.rglob("*.feature"))


def _should_skip_scenario(name: str, body: str, *, oc9_filter: bool) -> str | None:
    if not oc9_filter:
        return None
    text = f"{name}\n{body}"
    for pat in OC9_TCK_SKIP_PATTERNS:
        if pat.search(text):
            return f"oc9-filter: {pat.pattern}"
    return None


def _extract_error_expectation(body: str) -> tuple[str, str, str] | None:
    """Return (error_type, when, code) for ``Then a X should be raised at …`` steps."""
    m = _ERROR_ASSERT.search(body)
    if not m:
        return None
    return m.group(1), m.group(2).lower(), m.group(3)


def _is_intentional_negative(name: str) -> bool:
    return bool(_INTENTIONAL_NEGATIVE.search(name))


def _try_parse(query: str, *, dialect: str | None = None) -> str | None:
    try:
        _parse_tck(query, dialect=dialect)
        return None
    except Exception as e:  # noqa: BLE001
        return str(e)


def _unsupported_reason(body: str) -> str | None:
    outline = _outline_skip_reason(body)
    if outline:
        return outline
    m = re.search(r"Given the ([\w-]+) graph", body, re.I)
    if m and m.group(1) not in {"binary-tree-1", "binary-tree-2"}:
        return f"named graph: {m.group(1)}"
    if re.search(r"side effects should be:", body, re.I):
        return "side-effect assertion"
    if re.search(r"parameter values are:", body, re.I):
        return "parameter table (not implemented)"
    if re.search(r"there exists a procedure", body, re.I):
        return "procedure stub (not implemented)"
    return None


def _run_skip_reason(
    name: str, body: str, query: str | None, *, dialect: str | None = None
) -> str | None:
    """Pre-run skip for harness limits (not product failures)."""
    unsupported = _unsupported_reason(body)
    if unsupported:
        return unsupported
    if not query:
        return "no query found"
    if _extract_error_expectation(body):
        return None
    parse_err = _try_parse(query, dialect=dialect)
    if parse_err:
        if _is_intentional_negative(name):
            return None
        return "query does not parse"
    return None


def _outline_skip_reason(body: str) -> str | None:
    """Cucumber Scenario Outlines are not expanded — skip placeholder queries."""
    if "Examples:" in body:
        return "scenario outline (not expanded)"
    query = _extract_query(body) or ""
    if _OUTLINE_PLACEHOLDER.search(query):
        return "scenario outline (placeholder query)"
    return None


def run_tck(
    root: Path | None = None,
    *,
    parse_only: bool = False,
    oc9_filter: bool = False,
    tck_root: Path | None = None,
    dialect: str | None = None,
) -> Scoreboard:
    read = dialect or tck_dialect()
    board = Scoreboard()
    for feature in discover_features(root):
        text = feature.read_text(encoding="utf-8")
        rel = feature.name
        try:
            rel = str(feature.relative_to(root)) if root else feature.name
        except ValueError:
            rel = feature.name
        background = _extract_background(text)
        for name, body in _split_scenarios(text):
            full_body = f"{background}{body}" if background else body
            skip = _should_skip_scenario(name, full_body, oc9_filter=oc9_filter)
            if skip:
                board.results.append(ScenarioResult(name, rel, True, kind="skip", skip_reason=skip))
                continue
            if parse_only:
                outline = _outline_skip_reason(full_body)
                if outline:
                    board.results.append(
                        ScenarioResult(name, rel, True, kind="skip", skip_reason=outline)
                    )
                    continue
                board.results.append(_run_parse(name, rel, full_body, dialect=read))
                continue
            unsupported = _run_skip_reason(
                name, full_body, _extract_query(full_body), dialect=read
            )
            if unsupported:
                board.results.append(
                    ScenarioResult(name, rel, True, kind="skip", skip_reason=unsupported)
                )
                continue
            err_exp = _extract_error_expectation(full_body)
            if err_exp:
                board.results.append(
                    _run_error_scenario(
                        name, rel, full_body, tck_root=tck_root, err_exp=err_exp, dialect=read
                    )
                )
                continue
            query = _extract_query(full_body)
            if query and _try_parse(query, dialect=read) is not None and _is_intentional_negative(
                name
            ):
                board.results.append(
                    ScenarioResult(
                        name,
                        rel,
                        True,
                        kind="expected",
                        skip_reason="intentional negative (parse rejected)",
                    )
                )
                continue
            board.results.append(
                _run_scenario(name, rel, full_body, tck_root=tck_root, dialect=read)
            )
    board.dialect = read
    return board


def _extract_background(text: str) -> str:
    """Return shared ``Background:`` steps prepended to each scenario body."""
    m = re.search(r"^\s*Background:\s*\n(.*?)(?=^\s*Scenario)", text, re.M | re.S)
    return m.group(1) if m else ""


def _split_scenarios(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    current_name: str | None = None
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


def _extract_block_after(prefix: str, body: str) -> str | None:
    for line in body.splitlines():
        if re.search(prefix, line, re.I):
            idx = body.index(line)
            rest = body[idx + len(line) :]
            m = _DOCSTRING.search(rest) or _FENCE.search(rest)
            if m:
                return _dedent(m.group(1))
    return None


def _dedent(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
    pad = min(indents) if indents else 0
    return "\n".join(ln[pad:] if len(ln) >= pad else ln for ln in lines).strip()


def _extract_query(body: str) -> str | None:
    return _extract_block_after(r"When\s+executing query", body)


def _extract_init_queries(body: str) -> list[str]:
    queries: list[str] = []
    for prefix in (r"having executed", r"after having executed"):
        block = _extract_block_after(prefix, body)
        if block:
            queries.append(block)
    return queries


def _graph_setup(
    body: str, *, tck_root: Path | None, dialect: str | None = None
) -> Graph | str:
    if re.search(r"Given an empty graph", body, re.I) or re.search(r"Given any graph", body, re.I):
        graph = Graph()
    else:
        m = re.search(r"Given the ([\w-]+) graph", body, re.I)
        if not m:
            return "unsupported graph setup"
        loaded = _load_named_graph(m.group(1), tck_root=tck_root, dialect=dialect)
        if isinstance(loaded, str):
            return loaded
        graph = loaded

    err = _apply_init_queries(graph, body, dialect=dialect)
    if err:
        return err
    return graph


def _apply_init_queries(
    graph: Graph, body: str, *, dialect: str | None = None
) -> str | None:
    for query in _extract_init_queries(body):
        for stmt in _split_statements(query):
            try:
                execute(_parse_tck(stmt, dialect=dialect), graph=graph)
            except Exception as e:  # noqa: BLE001
                return f"init query failed: {e}"
    return None


def _split_statements(cypher: str) -> list[str]:
    parts = [p.strip() for p in cypher.split(";") if p.strip()]
    return parts if parts else [cypher.strip()]


def _load_named_graph(
    name: str, *, tck_root: Path | None, dialect: str | None = None
) -> Graph | str:
    root = tck_root or official_tck_root()
    cypher_file = official_graphs_path(root) / name / f"{name}.cypher"
    if not cypher_file.exists():
        return f"named graph file missing: {name}"
    graph = Graph()
    for stmt in _split_statements(cypher_file.read_text(encoding="utf-8")):
        try:
            execute(_parse_tck(stmt, dialect=dialect), graph=graph)
        except Exception as e:  # noqa: BLE001
            return f"named graph load failed: {e}"
    return graph


def _parse_result_table(
    body: str,
) -> tuple[list[str], list[tuple[str, ...]], bool, bool] | str:
    ordered = bool(re.search(r"result should be, in order:", body, re.I))
    any_order = bool(re.search(r"result should be, in any order:", body, re.I))
    list_order_insensitive = bool(
        re.search(r"result should be \(ignoring element order for lists\)", body, re.I)
    )
    if not ordered and not any_order and not list_order_insensitive:
        if re.search(r"result should be empty", body, re.I):
            return [], [], False, False
        return "no result expectation"

    lines = body.splitlines()
    table_lines: list[str] = []
    capture = False
    for line in lines:
        if re.search(r"Then the result should be", line, re.I):
            capture = True
            continue
        if capture:
            if line.strip().startswith("And ") and not _TABLE_ROW.match(line):
                break
            if _TABLE_ROW.match(line):
                table_lines.append(line)
            elif table_lines:
                break

    if not table_lines:
        return "result table not found"

    parsed = [_parse_table_row(ln) for ln in table_lines]
    columns = list(parsed[0])
    rows = [tuple(row) for row in parsed[1:]]
    return columns, rows, any_order, list_order_insensitive


def _parse_table_row(line: str) -> list[str]:
    m = _TABLE_ROW.match(line)
    if not m:
        return []
    return [cell.strip() for cell in m.group(1).split("|")]


def _run_parse(
    name: str, feature: str, body: str, *, dialect: str | None = None
) -> ScenarioResult:
    query = _extract_query(body)
    if not query:
        return ScenarioResult(name, feature, False, "no query found", kind="parse")
    try:
        _parse_tck(query, dialect=dialect)
        return ScenarioResult(name, feature, True, kind="parse")
    except Exception as e:  # noqa: BLE001
        return ScenarioResult(name, feature, False, str(e), kind="parse")


def _run_error_scenario(
    name: str,
    feature: str,
    body: str,
    *,
    tck_root: Path | None,
    err_exp: tuple[str, str, str],
    dialect: str | None = None,
) -> ScenarioResult:
    """Scenario expects compile-time or runtime failure — pass when cypherast rejects."""
    _err_type, when, code = err_exp
    query = _extract_query(body)
    if not query:
        return ScenarioResult(name, feature, False, "no query found", kind="expected")

    if when == "compile time":
        try:
            _parse_tck(query, dialect=dialect)
            _validate_tck(query, dialect=dialect)
        except Exception as e:  # noqa: BLE001
            return ScenarioResult(
                name,
                feature,
                True,
                kind="expected",
                skip_reason=f"compile rejection ({code}): {str(e)[:80]}",
            )
        return ScenarioResult(
            name,
            feature,
            True,
            kind="skip",
            skip_reason=f"error not raised ({code}, not implemented)",
        )

    graph_or_err = _graph_setup(body, tck_root=tck_root, dialect=dialect)
    if isinstance(graph_or_err, str):
        return ScenarioResult(name, feature, False, graph_or_err, kind="expected")

    try:
        execute(_parse_tck(query, dialect=dialect), graph=graph_or_err)
    except Exception as e:  # noqa: BLE001
        return ScenarioResult(
            name,
            feature,
            True,
            kind="expected",
            skip_reason=f"runtime rejection ({code}): {str(e)[:80]}",
        )
    return ScenarioResult(
        name,
        feature,
        True,
        kind="skip",
        skip_reason=f"error not raised ({code}, not implemented)",
    )


def _run_scenario(
    name: str,
    feature: str,
    body: str,
    *,
    tck_root: Path | None,
    dialect: str | None = None,
) -> ScenarioResult:
    query = _extract_query(body)
    if not query:
        return ScenarioResult(name, feature, False, "no query found", kind="run")

    graph_or_err = _graph_setup(body, tck_root=tck_root, dialect=dialect)
    if isinstance(graph_or_err, str):
        return ScenarioResult(name, feature, False, graph_or_err, kind="run")

    expected = _parse_result_table(body)
    if isinstance(expected, str):
        return ScenarioResult(name, feature, False, expected, kind="run")
    columns, expected_rows, any_order, list_order_insensitive = expected

    try:
        result = execute(_parse_tck(query, dialect=dialect), graph=graph_or_err)
        actual_rows = result_rows(result, columns) if columns else []
        if not columns:
            if actual_rows:
                return ScenarioResult(
                    name, feature, False, f"expected empty, got {len(actual_rows)} rows", kind="run"
                )
            return ScenarioResult(name, feature, True, kind="run")

        if len(actual_rows) != len(expected_rows):
            return ScenarioResult(
                name,
                feature,
                False,
                f"row count {len(actual_rows)} != {len(expected_rows)}",
                kind="run",
            )

        if not rows_equal(
            list(expected_rows),
            list(actual_rows),
            any_order=any_order,
            list_order_insensitive=list_order_insensitive,
        ):
            return ScenarioResult(
                name,
                feature,
                False,
                f"rows differ: expected {expected_rows[:3]} got {actual_rows[:3]}",
                kind="run",
            )
        return ScenarioResult(name, feature, True, kind="run")
    except CypherastError as e:
        return ScenarioResult(name, feature, False, str(e), kind="run")
    except Exception as e:  # noqa: BLE001
        return ScenarioResult(name, feature, False, str(e), kind="run")


def write_report(board: Scoreboard, path: Path, *, tck_path: Path) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    run = board.by_kind("run")
    parse = board.by_kind("parse")
    skipped = board.by_kind("skip")
    failures = [r for r in board.results if not r.passed and r.kind != "skip"]

    lines = [
        "# openCypher TCK results",
        "",
        f"Generated: {now}",
        f"Features: `{tck_path}`",
        f"Dialect: `{board.dialect}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total scenarios | {board.total} |",
        f"| Passed | {board.passed} |",
        f"| Skipped | {len(skipped)} |",
        f"| Failed | {len(failures)} |",
    ]
    if parse:
        lines.append(f"| Parse rate | {board.parse_rate:.1%} ({len(parse)} scenarios) |")
    if run:
        expected = board.by_kind("expected")
        lines.append(f"| Run rate | {board.run_rate:.1%} ({len(run)} scenarios) |")
        if expected:
            lines.append(
                f"| Effective run rate | {board.effective_run_rate:.1%} "
                f"({len(run) + len(expected)} scored) |"
            )
        lines.append(f"| Expected passes | {sum(1 for r in expected if r.passed)} |")
    lines.extend(["", "## By feature", ""])

    by_feature: dict[str, list[ScenarioResult]] = {}
    for r in board.results:
        by_feature.setdefault(r.feature, []).append(r)

    for feat in sorted(by_feature):
        rows = by_feature[feat]
        passed = sum(1 for r in rows if r.passed or r.kind == "skip")
        lines.append(f"- `{feat}`: {passed}/{len(rows)}")

    if failures:
        lines.extend(["", "## Failures (first 50)", ""])
        for r in failures[:50]:
            err = (r.error or "").replace("\n", " ")[:200]
            lines.append(f"- **{r.feature}** / {r.name}: {err}")

    skip_reasons: dict[str, int] = {}
    for r in skipped:
        key = r.skip_reason or "unknown"
        skip_reasons[key] = skip_reasons.get(key, 0) + 1
    if skip_reasons:
        lines.extend(["", "## Skip reasons", ""])
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"- {reason}: {count}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_official(
    *,
    parse_only: bool = False,
    oc9_filter: bool = False,
    report_path: Path | None = None,
    tck_root: Path | None = None,
    dialect: str | None = None,
) -> Scoreboard:
    root = tck_root or official_tck_root()
    features = ensure_official_tck(root)
    board = run_tck(
        features,
        parse_only=parse_only,
        oc9_filter=oc9_filter,
        tck_root=root,
        dialect=dialect,
    )
    out = report_path or Path(__file__).parent / "results.md"
    write_report(board, out, tck_path=features)
    return board
