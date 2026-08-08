"""TCK dialect transpose gate — OC9-passing scenarios on other dialects."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.tck.fetch import ensure_official_tck
from tests.tck.runner import (
    dialect_matrix_gate_failures,
    run_official_dialect_matrix,
)


@pytest.fixture(scope="module")
def official_features() -> Path:
    if os.environ.get("CYPHERAST_TCK_SKIP"):
        pytest.skip("CYPHERAST_TCK_SKIP set")
    return ensure_official_tck()


def test_tck_dialect_matrix(official_features: Path, tmp_path: Path) -> None:
    oc9 = os.environ.get("CYPHERAST_TCK_OC9_FILTER", "").lower() in {"1", "true", "yes"}
    # Report goes to tmp_path; the repo-relative path belongs to the Make target.
    board = run_official_dialect_matrix(oc9_filter=oc9, report_path=tmp_path / "results.md")
    baseline_run = [r for r in board.baseline.by_kind("run") if r.passed]
    assert len(baseline_run) > 50, board.summary()

    # Same helper as the CLI gate: run-rate floors plus executable-count and
    # skip-ratio guards, so mass capability skips cannot pass on rate alone.
    gate = dialect_matrix_gate_failures(board)
    assert gate == [], f"{gate} | {board.summary()}"
