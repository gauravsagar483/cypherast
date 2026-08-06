"""TCK parse-rate scoreboard against sample .feature files."""

from pathlib import Path

from tests.tck.runner import discover_features, run_tck

FEATURES = Path(__file__).parent / "features"


def test_discover_features():
    found = discover_features(FEATURES)
    assert len(found) >= 3
    assert any(p.name == "MatchAcceptance.feature" for p in found)


def test_tck_parse_rate_scoreboard():
    board = run_tck(FEATURES, parse_only=True)
    assert board.total >= 15
    # Hard floor while grammar hardens — raise as coverage grows
    assert board.parse_rate >= 0.7, board.summary()
    print(board.summary())
    failed = [r for r in board.results if not r.passed]
    for r in failed[:10]:
        print(f"FAIL {r.feature}::{r.name}: {r.error}")
