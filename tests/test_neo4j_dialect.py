"""Neo4j dialect matrix (neo4j5 / neo4j25 aliases) — always pass explicit dialect."""

from __future__ import annotations

import pytest

import cypherast
from cypherast import ast as a
from cypherast.dialects.dialect import get_dialect_cls
from cypherast.dialects.neo4j import Neo4jCypher5, Neo4jCypher25
from cypherast.errors import CompatibilityError, ParseError, ValidationError


@pytest.mark.parametrize("dialect", ["neo4j25", "neo4j", "neo", "neo4j5", "cypher5"])
def test_registry_aliases(dialect: str) -> None:
    cls = get_dialect_cls(dialect)
    if dialect in ("neo4j25", "neo4j", "neo"):
        assert cls is Neo4jCypher25
    else:
        assert cls is Neo4jCypher5


def test_neo4j25_pattern_predicate_exists_style() -> None:
    q = "MATCH (n:Person) WHERE (n)-[:KNOWS]->(:Person) RETURN n"
    out = cypherast.parse_one(q, read="neo4j25").cypher(dialect="neo4j25")
    assert "EXISTS" in out


def test_call_variable_import_neo4j5() -> None:
    q = "MATCH (n) CALL (n) { WITH n RETURN n } RETURN n"
    tree = cypherast.parse_one(q, read="neo4j5")
    call = tree.find(a.CallSubquery)
    assert call is not None
    assert call.variables is not None
    issues = cypherast.validate(tree, dialect="neo4j5")
    assert not issues


def test_inline_pattern_where_neo4j5() -> None:
    q = "MATCH (n:Person WHERE n.age > 18) RETURN n.name"
    tree = cypherast.parse_one(q, read="neo4j5")
    node = tree.find(a.NodePattern)
    assert node is not None
    assert node.where is not None
    issues = cypherast.validate(tree, dialect="neo4j5")
    assert not issues


def test_inline_relationship_where_rejected_without_capability() -> None:
    q = "MATCH (n)-[r:KNOWS WHERE r.since > 2020]->(m) RETURN m"
    tree = cypherast.parse_one(q, read="neo4j5")
    rel = tree.find(a.RelationshipPattern)
    assert rel is not None
    assert rel.where is not None
    assert not cypherast.validate(tree, dialect="neo4j5")
    issues = cypherast.validate(tree, dialect="opencypher")
    assert any(i.code == "CG1401" for i in issues)


def test_for_clause_is_gated_separately_from_filter() -> None:
    q = "FOR n IN [1, 2] RETURN n"
    tree = cypherast.parse_one(q, read="neo4j25")
    assert tree.find(a.For) is not None
    assert not cypherast.validate(tree, dialect="neo4j25")
    issues = cypherast.validate(tree, dialect="neo4j5")
    assert any(i.code == "CG1520" and "FOR" in i.message for i in issues)


def test_load_csv_neo4j5() -> None:
    q = "LOAD CSV WITH HEADERS FROM 'file:///tmp/x.csv' AS row RETURN row"
    tree = cypherast.parse_one(q, read="neo4j5")
    assert tree.find(a.LoadCsv) is not None
    issues = cypherast.validate(tree, dialect="neo4j5")
    assert not issues


def test_filter_neo4j25_only() -> None:
    q = "MATCH (n:Person) FILTER (n WHERE n.age > 18) RETURN n"
    tree = cypherast.parse_one(q, read="neo4j25")
    assert tree.find(a.Filter) is not None
    issues = cypherast.validate(tree, dialect="neo4j25")
    assert not issues
    issues5 = cypherast.validate(tree, dialect="neo4j5")
    assert any(i.code == "CG1520" for i in issues5)


def test_filter_rejected_on_neo4j5_parse() -> None:
    q = "MATCH (n) FILTER (n WHERE n.x > 1) RETURN n"
    with pytest.raises(ParseError):
        cypherast.parse_one(q, read="neo4j5")


def test_optional_call_in_transactions_neo4j25() -> None:
    q = "OPTIONAL CALL (x) { RETURN 1 AS x } IN TRANSACTIONS OF 1000 ROWS RETURN x"
    tree = cypherast.parse_one(q, read="neo4j25")
    call = tree.find(a.CallSubquery)
    assert call is not None
    assert call.optional
    assert call.in_transactions
    issues = cypherast.validate(tree, dialect="neo4j25")
    assert not issues


def test_group_by_neo4j25() -> None:
    q = "MATCH (n:Person) RETURN n.city, count(n) GROUP BY n.city"
    tree = cypherast.parse_one(q, read="neo4j25")
    ret = tree.find(a.Return)
    assert ret is not None
    assert ret.group_by is not None
    issues = cypherast.validate(tree, dialect="neo4j25")
    assert not issues


@pytest.mark.parametrize(
    "q",
    [
        "MATCH (n:Person) RETURN n.city AS c, count(n) AS k GROUP BY n.city ORDER BY c LIMIT 3",
        "MATCH (n:Person) WITH n.city AS c, count(n) AS k GROUP BY n.city ORDER BY c RETURN c",
    ],
)
def test_group_by_precedes_order_tail(q: str) -> None:
    """GROUP BY comes before ORDER BY / SKIP / LIMIT, and renders back in that order."""
    assert cypherast.parse_one(q, read="neo4j25").cypher(dialect="neo4j25") == q


@pytest.mark.parametrize(
    "q",
    [
        "MATCH (n) FILTER (n WHERE n.x > 1) RETURN n",
        "MATCH (n) LET x = n.a RETURN x",
        "FOR n IN [1, 2] RETURN n",
        "MATCH (n) RETURN n.c AS c, count(*) AS k GROUP BY n.c",
        "LOAD CSV FROM 'f.csv' AS row RETURN row",
        "WHEN true THEN { RETURN 1 AS x }",
    ],
)
def test_cypher25_surface_is_not_rendered_for_opencypher(q: str) -> None:
    """A target that cannot express the construct must raise, not emit invalid text."""
    tree = cypherast.parse_one(q, read="neo4j25")
    with pytest.raises(CompatibilityError):
        tree.cypher(dialect="opencypher")


def test_when_branches_are_visible_to_traversal() -> None:
    """Branch bodies must be AST children, or every pass would silently skip them."""
    q = "WHEN true THEN { MATCH (n:Person) RETURN n } ELSE { RETURN 0 AS n }"
    tree = cypherast.parse_one(q, read="neo4j25")
    assert tree.find(a.Match) is not None
    assert len(list(tree.find_all(a.WhenBranch))) == 1
    assert tree.cypher(dialect="neo4j25") == q


def test_opencypher_rejects_call_subquery() -> None:
    q = "MATCH (n) CALL { RETURN n } RETURN n"
    issues = cypherast.validate(q, read="opencypher", dialect="opencypher")
    assert any(i.code == "CG1505" for i in issues)


def test_neo4j25_accepts_qpp() -> None:
    q = "MATCH ((n:Person)-[:KNOWS]->(m)){1,3} RETURN n, m"
    tree = cypherast.parse_one(q, read="neo4j25")
    issues = cypherast.validate(tree, dialect="neo4j25")
    assert not any(i.code == "CG1508" for i in issues)


def test_transpile_neo4j25_to_neo4j5_filter_raises() -> None:
    q = "MATCH (n) FILTER (n WHERE n.x > 1) RETURN n"
    tree = cypherast.parse_one(q, read="neo4j25")
    with pytest.raises(ValidationError):
        cypherast.optimize(tree, read="neo4j25", write="neo4j5", strict=True)
