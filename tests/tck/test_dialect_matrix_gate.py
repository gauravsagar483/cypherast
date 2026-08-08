"""CLI exit semantics for `python -m tests.tck --dialect-matrix`.

The matrix gate is rate-based: individual transpose failures are expected, so exit
status follows the per-dialect run-rate floors, not the presence of any failure.
Rates alone can be gamed by skipping scenarios, so the gate also enforces a minimum
executable count and a maximum skip ratio per target.
Official TCK is never invoked here — the board is built in-memory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import tests.tck.__main__ as tck_main
from tests.tck.runner import (
    DIALECT_MATRIX_FLOORS,
    DIALECT_MATRIX_MAX_SKIP_RATIO,
    DIALECT_MATRIX_MIN_EXECUTABLE,
    DIALECT_MATRIX_TARGETS,
    DialectMatrixBoard,
    DialectMatrixResult,
    Scoreboard,
    dialect_matrix_gate_failures,
)


def _rows(dialect: str, *, passed: int, failed: int, skipped: int = 0) -> list[DialectMatrixResult]:
    rows = [
        DialectMatrixResult(f"pass-{i}", "f.feature", dialect, True, kind="run")
        for i in range(passed)
    ]
    rows += [
        DialectMatrixResult(f"fail-{i}", "f.feature", dialect, False, "boom", kind="run")
        for i in range(failed)
    ]
    rows += [
        DialectMatrixResult(
            f"skip-{i}", "f.feature", dialect, True, kind="skip", skip_reason="capability"
        )
        for i in range(skipped)
    ]
    return rows


def _board(
    counts: dict[str, tuple[int, int, int]],
    *,
    targets: tuple[str, ...] = DIALECT_MATRIX_TARGETS,
) -> DialectMatrixBoard:
    board = DialectMatrixBoard(baseline=Scoreboard(), targets=targets)
    for dialect, (passed, failed, skipped) in counts.items():
        board.results.extend(_rows(dialect, passed=passed, failed=failed, skipped=skipped))
    return board


# Measured baseline 2026-08-08 (tests/tck/results-dialects.md): the gate must pass
# on the numbers we actually observe, so thresholds never depend on synthetic sizes.
_ABOVE_FLOORS: dict[str, tuple[int, int, int]] = {
    "neo4j5": (552, 17, 0),
    "neo4j25": (552, 17, 0),
    "memgraph": (552, 17, 0),
    "puppygraph": (287, 196, 86),
}


def _patch_matrix(monkeypatch: pytest.MonkeyPatch, board: DialectMatrixBoard) -> None:
    def fake_run(**kwargs: object) -> DialectMatrixBoard:
        return board

    monkeypatch.setattr(tck_main, "run_official_dialect_matrix", fake_run)


def test_thresholds_are_shared_between_cli_and_pytest_gate() -> None:
    for limits in (
        DIALECT_MATRIX_FLOORS,
        DIALECT_MATRIX_MIN_EXECUTABLE,
        DIALECT_MATRIX_MAX_SKIP_RATIO,
    ):
        assert set(limits) == set(DIALECT_MATRIX_TARGETS)


def test_gate_passes_on_measured_baseline_despite_failures() -> None:
    board = _board(_ABOVE_FLOORS)
    assert any(not r.passed for r in board.results)
    assert dialect_matrix_gate_failures(board) == []


def test_gate_reports_dialect_below_floor() -> None:
    counts = dict(_ABOVE_FLOORS)
    counts["memgraph"] = (300, 267, 0)
    failures = dialect_matrix_gate_failures(_board(counts))
    assert len(failures) == 1
    assert "memgraph" in failures[0]


def test_gate_reports_mass_capability_skips_at_full_run_rate() -> None:
    """A 100% run rate must not excuse skipping most of the matrix."""
    counts = dict(_ABOVE_FLOORS)
    counts["puppygraph"] = (420, 0, 300)
    failures = dialect_matrix_gate_failures(_board(counts))
    assert len(failures) == 1
    assert "puppygraph" in failures[0]
    assert "skip" in failures[0].lower()


def test_gate_reports_executable_count_below_minimum_at_full_run_rate() -> None:
    counts = dict(_ABOVE_FLOORS)
    counts["neo4j25"] = (120, 0, 0)
    failures = dialect_matrix_gate_failures(_board(counts))
    assert len(failures) == 1
    assert "neo4j25" in failures[0]
    assert "executable" in failures[0].lower()


def test_gate_reports_target_missing_skip_thresholds() -> None:
    targets = (*DIALECT_MATRIX_TARGETS, "mystery")
    counts = dict(_ABOVE_FLOORS)
    counts["mystery"] = (600, 0, 0)
    failures = dialect_matrix_gate_failures(
        _board(counts, targets=targets),
        floors={**DIALECT_MATRIX_FLOORS, "mystery": 0.9},
    )
    assert len(failures) == 1
    assert "mystery" in failures[0]
    assert "threshold" in failures[0].lower()


def test_gate_reports_dialect_with_no_executable_scenarios() -> None:
    counts = dict(_ABOVE_FLOORS)
    counts["puppygraph"] = (0, 0, 12)
    failures = dialect_matrix_gate_failures(_board(counts))
    assert len(failures) == 1
    assert "puppygraph" in failures[0]


def test_gate_reports_target_missing_floor() -> None:
    targets = (*DIALECT_MATRIX_TARGETS, "mystery")
    counts = dict(_ABOVE_FLOORS)
    counts["mystery"] = (100, 0, 0)
    failures = dialect_matrix_gate_failures(_board(counts, targets=targets))
    assert len(failures) == 1
    assert "mystery" in failures[0]
    assert "no floor" in failures[0].lower()


def test_cli_exits_zero_when_rates_clear_floors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_matrix(monkeypatch, _board(_ABOVE_FLOORS))
    assert tck_main.main(["--dialect-matrix", "--report", str(tmp_path / "r.md")]) == 0


def test_cli_exits_one_when_dialect_below_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    counts = dict(_ABOVE_FLOORS)
    counts["puppygraph"] = (100, 362, 105)
    _patch_matrix(monkeypatch, _board(counts))
    assert tck_main.main(["--dialect-matrix", "--report", str(tmp_path / "r.md")]) == 1
    assert "puppygraph" in capsys.readouterr().out


def test_cli_exits_one_when_skips_inflate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    counts = dict(_ABOVE_FLOORS)
    counts["memgraph"] = (520, 0, 300)
    _patch_matrix(monkeypatch, _board(counts))
    assert tck_main.main(["--dialect-matrix", "--report", str(tmp_path / "r.md")]) == 1
    assert "memgraph" in capsys.readouterr().out


def test_cli_exits_one_when_dialect_has_no_executable_scenarios(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    counts = dict(_ABOVE_FLOORS)
    counts["neo4j25"] = (0, 0, 5)
    _patch_matrix(monkeypatch, _board(counts))
    assert tck_main.main(["--dialect-matrix", "--report", str(tmp_path / "r.md")]) == 1
