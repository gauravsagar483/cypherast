"""TCK infrastructure smoke tests (no local .feature files)."""

from pathlib import Path

from tests.tck.compare import normalize_cell, rows_equal
from tests.tck.runner import (
    DIALECT_MATRIX_TARGETS,
    Scoreboard,
    _extract_error_expectation,
    _outline_skip_reason,
    _parse_result_table,
    _parse_tck,
    _run_skip_reason,
    discover_features,
    run_dialect_matrix,
    run_tck,
    tck_dialect,
)


def test_discover_empty():
    assert discover_features(Path("/nonexistent/tck")) == []


def test_scoreboard_summary():
    board = Scoreboard()
    assert "0/0" in board.summary()


def test_run_tck_noop():
    board = run_tck(Path("/nonexistent/tck"), parse_only=True)
    assert board.total == 0


def test_run_dialect_matrix_noop():
    board = run_dialect_matrix(Path("/nonexistent/tck"))
    assert board.baseline.total == 0
    assert board.results == []
    summary = board.summary()
    for target in DIALECT_MATRIX_TARGETS:
        assert f"{target}=0.0%" in summary


def test_outline_skip_detects_placeholder():
    body = 'When executing query:\n"""\nRETURN all(x IN <list> WHERE x)\n"""\n'
    assert _outline_skip_reason(body) == "scenario outline (placeholder query)"


def test_outline_skip_detects_examples():
    body = 'When executing query:\n"""\nRETURN 1\n"""\n\nExamples:\n| a |\n'
    assert _outline_skip_reason(body) == "scenario outline (not expanded)"


def test_parse_result_table_ignoring_list_order():
    body = """
    Then the result should be (ignoring element order for lists):
      | r            |
      | [[:X], [:Y]] |
    """
    parsed = _parse_result_table(body)
    assert not isinstance(parsed, str)
    cols, rows, any_order, list_insensitive = parsed
    assert cols == ["r"]
    assert rows == [("[[:X], [:Y]]",)]
    assert list_insensitive is True
    assert any_order is False


def test_normalize_node_label_order():
    a = "(:Z:Y:X:W:V:U)"
    b = "(:U:V:W:X:Y:Z)"
    assert normalize_cell(a) == normalize_cell(b)


def test_rows_equal_list_order_insensitive():
    exp = [("[[:X], [:Y]]",)]
    act = [("[[:Y], [:X]]",)]
    assert rows_equal(exp, act, any_order=False, list_order_insensitive=True)


def test_extract_error_expectation():
    body = """
    When executing query:
      \"\"\"
      RETURN 1
      \"\"\"
    Then a SyntaxError should be raised at compile time: UndefinedVariable
    """
    assert _extract_error_expectation(body) == ("SyntaxError", "compile time", "UndefinedVariable")


def test_run_skip_reason_unparseable():
    body = """
    When executing query:
      \"\"\"
      RETURN 0x1
      \"\"\"
    Then the result should be, in any order:
      | v |
    """
    reason = _run_skip_reason("hex literal", body, "RETURN 0x1")
    assert reason == "query does not parse"


def test_run_skip_reason_procedure_stub():
    body = """
    And there exists a procedure test.my.proc() :: ():
    When executing query:
      \"\"\"
      CALL test.my.proc()
      \"\"\"
    """
    assert (
        _run_skip_reason("proc", body, "CALL test.my.proc()") == "procedure stub (not implemented)"
    )


def test_parse_tck_uses_read_dialect(monkeypatch):
    monkeypatch.setenv("CYPHERAST_TCK_DIALECT", "opencypher")
    assert tck_dialect() == "opencypher"
    tree = _parse_tck("MATCH (n) RETURN n")
    assert tree.cypher(dialect="opencypher").startswith("MATCH")


def test_run_dialect_transpose_passes_target_dialect_to_execute(monkeypatch) -> None:
    """Matrix target execution must lower via execute(..., dialect=target)."""
    import tests.tck.runner as runner
    from cypherast.executor.engine import execute as real_execute

    captured: list[str | None] = []

    def tracking_execute(tree, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs.get("dialect"))
        return real_execute(tree, *args, **kwargs)

    monkeypatch.setattr(runner, "execute", tracking_execute)

    query = "MATCH (n:Person) RETURN n.name AS name"
    body = f'''
    Given an empty graph
    And having executed:
      """
      CREATE (:Person {{name: 'Ada'}})
      """
    When executing query:
      """
      {query}
      """
    Then the result should be, in any order:
      | name |
      | 'Ada' |
    '''
    result = runner._run_dialect_transpose(
        "simple match",
        "smoke.feature",
        body,
        query,
        dialect="neo4j25",
        tck_root=None,
    )
    assert result.passed, result.error
    # Init CREATE is one setup execute without dialect; only the final target call gets neo4j25.
    assert len(captured) >= 2, captured
    setup, target = captured[:-1], captured[-1]
    assert setup, captured
    assert all(d is None for d in setup), setup
    assert target == "neo4j25"
