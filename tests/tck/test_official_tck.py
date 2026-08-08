"""Official openCypher TCK — clones to /tmp, runs executor, writes results.md."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.tck.fetch import ensure_official_tck
from tests.tck.runner import run_official

RESULTS = Path(__file__).parent / "results.md"


@pytest.fixture(scope="module")
def official_features() -> Path:
    if os.environ.get("CYPHERAST_TCK_SKIP"):
        pytest.skip("CYPHERAST_TCK_SKIP set")
    return ensure_official_tck()


def test_official_tck_parse_gate(official_features: Path) -> None:
    oc9 = os.environ.get("CYPHERAST_TCK_OC9_FILTER", "").lower() in {"1", "true", "yes"}
    board = run_official(parse_only=True, oc9_filter=oc9, report_path=RESULTS)
    assert board.total > 100, board.summary()
    assert board.parse_rate >= 0.85, board.summary()


def test_official_tck_executor(official_features: Path) -> None:
    oc9 = os.environ.get("CYPHERAST_TCK_OC9_FILTER", "").lower() in {"1", "true", "yes"}
    board = run_official(parse_only=False, oc9_filter=oc9, report_path=RESULTS)
    run = board.by_kind("run")
    assert len(run) > 50, board.summary()
    # Run rate on executable scenarios; effective includes expected-error passes
    assert board.run_rate >= 0.58, board.summary()
    assert board.effective_run_rate >= 0.62, board.summary()
