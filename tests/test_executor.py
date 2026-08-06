"""Executor tests."""

import cypherglot
from cypherglot.executor import Graph


def _graph() -> Graph:
    g = Graph()
    ada = g.create_node(["Person"], name="Ada", age=36)
    alan = g.create_node(["Person"], name="Alan", age=42)
    g.create_node(["Person"], name="Grace", age=25)
    g.create_rel(ada, alan, "KNOWS", since=1950)
    return g


def test_match_return():
    g = _graph()
    result = cypherglot.run("MATCH (n:Person) RETURN n.name", graph=g)
    vals = sorted(list(row.values())[0] for row in result)
    assert vals == ["Ada", "Alan", "Grace"]


def test_where():
    g = _graph()
    result = cypherglot.run("MATCH (n:Person) WHERE n.age > 30 RETURN n.name AS name", graph=g)
    names = sorted(row["name"] for row in result)
    assert names == ["Ada", "Alan"]


def test_expand():
    g = _graph()
    result = cypherglot.run(
        "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name AS a, b.name AS b",
        graph=g,
    )
    rows = list(result)
    assert len(rows) == 1
    assert rows[0]["a"] == "Ada"
    assert rows[0]["b"] == "Alan"


def test_create():
    g = Graph()
    cypherglot.run("CREATE (n:Person {name: 'Ada'})", graph=g)
    assert len(g.all_nodes()) == 1
    assert g.all_nodes()[0]["name"] == "Ada"


def test_count():
    g = _graph()
    result = cypherglot.run("MATCH (n:Person) RETURN count(n) AS c", graph=g)
    rows = list(result)
    assert rows[0]["c"] == 3


def test_unwind():
    g = Graph()
    result = cypherglot.run("UNWIND [1, 2, 3] AS x RETURN x", graph=g)
    assert [row["x"] for row in result] == [1, 2, 3]
