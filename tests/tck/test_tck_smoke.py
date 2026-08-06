"""TCK scoreboard smoke (no features shipped yet)."""

from pathlib import Path

from tests.tck.runner import Scoreboard, discover_features, run_tck


def test_discover_empty():
    assert discover_features(Path("/nonexistent/tck")) == []


def test_scoreboard_summary():
    board = Scoreboard()
    assert "0/0" in board.summary()


def test_run_tck_noop():
    board = run_tck(Path("/nonexistent/tck"), parse_only=True)
    assert board.total == 0
