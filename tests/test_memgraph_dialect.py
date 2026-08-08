"""Memgraph dialect fixtures — always pass explicit dialect."""

from __future__ import annotations

import pytest

import cypherast
from cypherast import ast as a
from cypherast.dialects.dialect import get_dialect_cls
from cypherast.dialects.memgraph import Memgraph
from cypherast.errors import CompatibilityError, ParseError


def test_memgraph_extends_neo4j5() -> None:
    assert issubclass(Memgraph, get_dialect_cls("neo4j5"))
    assert Memgraph.capabilities.reject_quantified_path
    assert Memgraph.capabilities.allow_memgraph_rel_quantifiers


def test_call_subquery_with_import() -> None:
    q = "MATCH (n) CALL (n) { WITH n RETURN n } RETURN n"
    tree = cypherast.parse_one(q, read="memgraph")
    call = tree.find(a.CallSubquery)
    assert call is not None
    issues = cypherast.validate(tree, dialect="memgraph")
    assert not issues


def test_load_csv_memgraph() -> None:
    q = "LOAD CSV FROM 'file:///data.csv' AS row RETURN row"
    tree = cypherast.parse_one(q, read="memgraph")
    assert tree.find(a.LoadCsv) is not None
    issues = cypherast.validate(tree, dialect="memgraph")
    assert not issues


def test_bfs_quantifier() -> None:
    q = "MATCH (a)-[*bfs..10]->(b) RETURN a, b"
    tree = cypherast.parse_one(q, read="memgraph")
    rel = tree.find(a.RelationshipPattern)
    assert rel is not None
    assert rel.memgraph_quantifier == "bfs"
    out = tree.cypher(dialect="memgraph")
    assert "*bfs" in out


def test_wshortest_quantifier_round_trips() -> None:
    q = "MATCH (a)-[*wShortest (e, n | e.weight) total]->(b) RETURN a, b"
    tree = cypherast.parse_one(q, read="memgraph")
    rel = tree.find(a.RelationshipPattern)
    assert rel is not None
    assert rel.memgraph_quantifier == "wShortest"
    # The weight lambda is real expression nodes, not captured token text.
    assert rel.memgraph_weight_expr is not None
    assert isinstance(rel.memgraph_weight_expr, a.RelationshipLambda)
    assert rel.memgraph_total_weight is not None
    assert not cypherast.validate(tree, dialect="memgraph")
    assert tree.cypher(dialect="memgraph") == q


def test_wshortest_with_hop_bound_round_trips() -> None:
    q = "MATCH (a)-[r:KNOWS*wShortest 5 (e, n | e.weight) total]->(b) RETURN b"
    tree = cypherast.parse_one(q, read="memgraph")
    assert tree.cypher(dialect="memgraph") == q


def test_unterminated_wshortest_lambda_raises() -> None:
    with pytest.raises(ParseError):
        cypherast.parse_one("MATCH (a)-[*wShortest (e, n", read="memgraph")


def test_memgraph_quantifier_not_rendered_for_other_dialects() -> None:
    tree = cypherast.parse_one("MATCH (a)-[*bfs..3]->(b) RETURN b", read="memgraph")
    with pytest.raises(CompatibilityError):
        tree.cypher(dialect="neo4j25")


def test_qpp_rejected_on_memgraph() -> None:
    q = "MATCH ((n)-[:R]->(m)){1,2} RETURN n"
    issues = cypherast.validate(q, read="memgraph", dialect="memgraph")
    assert any(i.code == "CG1510" for i in issues)


def test_bfs_rejected_on_neo4j25() -> None:
    q = "MATCH (a)-[*bfs..5]->(b) RETURN a"
    tree = cypherast.parse_one(q, read="memgraph")
    issues = cypherast.validate(tree, dialect="neo4j25")
    assert any(i.code == "CG1521" for i in issues)


@pytest.mark.parametrize(
    "q",
    [
        "CREATE INDEX ON :Person(name)",
        "CREATE CONSTRAINT ON (n:Person) ASSERT n.name IS UNIQUE",
        "SHOW INDEX INFO",
    ],
)
def test_admin_statements_pass_through_verbatim(q: str) -> None:
    tree = cypherast.parse_one(q, read="memgraph")
    assert tree.find(a.AdminStatement) is not None
    assert tree.cypher(dialect="memgraph") == q
