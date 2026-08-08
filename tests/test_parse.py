"""Parse / render roundtrip tests."""

import pytest

import cypherast

QUERIES = [
    "MATCH (n) RETURN n",
    "MATCH (n:Person) WHERE n.age > 30 RETURN n.name",
    "MATCH (a)-[:KNOWS]->(b) RETURN a, b",
    "MATCH (a)-[r:KNOWS*1..3]->(b) RETURN r",
    "CREATE (n:Person {name: 'Ada'}) RETURN n",
    "MERGE (n:Person {name: 'Ada'}) ON CREATE SET n.created = true RETURN n",
    "MATCH (n) WITH n ORDER BY n.name SKIP 1 LIMIT 2 RETURN n",
    "UNWIND [1, 2, 3] AS x RETURN x",
    "MATCH (n) RETURN count(n)",
    "MATCH (n) RETURN n.name AS name",
    "RETURN 1 + 2 * 3",
    "RETURN true AND false OR NOT true",
    "RETURN null IS NULL",
    "MATCH (n) WHERE n.name STARTS WITH 'A' RETURN n",
    "MATCH p = (a)-[:KNOWS]->(b) RETURN p",
]


@pytest.mark.parametrize("read", ["opencypher", "neo4j", "memgraph", "puppygraph", "opencypher9"])
def test_parse_smoke(read: str):
    for q in QUERIES:
        tree = cypherast.parse_one(q, read=read)
        assert tree is not None
        rendered = tree.cypher()
        assert isinstance(rendered, str)
        assert len(rendered) > 0


def test_roundtrip_basic():
    q = "MATCH (n:Person) WHERE n.age > 30 RETURN n.name"
    tree = cypherast.parse_one(q)
    out = tree.cypher()
    tree2 = cypherast.parse_one(out)
    assert tree2.cypher() == out


def test_translate_identity():
    q = "MATCH (n) RETURN n"
    assert "MATCH" in cypherast.translate(q, from_="opencypher", to_="neo4j")


def test_puppygraph_inherits_opencypher():
    from cypherast.dialects.opencypher import OpenCypher
    from cypherast.dialects.puppygraph import PuppyGraph, PuppyGraphRenderer

    assert issubclass(PuppyGraph, OpenCypher)
    assert "puppygraph" in cypherast.dialect_names()
    q = "MATCH (n:Person)-[:KNOWS]->(m) RETURN n.name"
    out = cypherast.translate(q, from_="opencypher", to_="puppygraph", pretty=True)
    assert "MATCH" in out
    assert PuppyGraph.renderer().dialect_name == "puppygraph"
    assert isinstance(PuppyGraph.renderer(), PuppyGraphRenderer)


def test_pretty():
    q = "MATCH (n) WHERE n.x = 1 RETURN n"
    out = cypherast.translate(q, pretty=True)
    assert "\n" in out or "WHERE" in out
