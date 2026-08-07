"""Remaining bug-bash debt: shared parse/render + in-memory executor."""

from __future__ import annotations

import cypherast
from cypherast import ast as a
from cypherast.executor import Graph

# --- BB-12 / BB-21 shared parse-render --------------------------------------


def test_bb12_remove_label_roundtrip():
    q = "MATCH (n:Person) REMOVE n:Person RETURN n"
    once = cypherast.parse_one(q).cypher()
    assert "REMOVE n:Person" in once.replace(" ", "") or "REMOVE n:Person" in once
    assert "EXISTS" not in once.upper()
    twice = cypherast.parse_one(once).cypher()
    assert "EXISTS" not in twice.upper()
    assert "REMOVE" in twice.upper() and "Person" in twice


def test_bb12_remove_labels_ast():
    tree = cypherast.parse_one("MATCH (n:Person:Temp) REMOVE n:Temp RETURN n")
    rem = tree.find(a.RemoveLabels)
    assert rem is not None
    assert isinstance(rem, a.RemoveLabels)


def test_bb21_map_projection_property_selector():
    out = cypherast.parse_one("RETURN n{.name}").cypher()
    assert out == "RETURN n{.name}" or "n{.name}" in out
    tree = cypherast.parse_one("RETURN n{.name}")
    mp = tree.find(a.MapProjection)
    assert mp is not None
    assert any(isinstance(e, a.PropertySelector) for e in mp.entries)
    # bare variable shorthand stays without dot
    out2 = cypherast.parse_one("RETURN n{name}").cypher()
    assert "n{name}" in out2.replace(" ", "") or out2.endswith("n{name}")


# --- Executor ---------------------------------------------------------------


def _people() -> Graph:
    g = Graph()
    alice = g.create_node(["person"], name="Alice")
    bob = g.create_node(["person"], name="Bob", age=20)
    g.create_rel(alice, bob, "knows")
    return g


def test_bb03_optional_where_keeps_outer_row():
    g = _people()
    rows = list(
        cypherast.run(
            "MATCH (a:person {name:'Alice'}) "
            "OPTIONAL MATCH (a)-[:knows]->(b:person) WHERE b.age > 100 "
            "RETURN a.name AS an, b.name AS bn",
            graph=g,
        )
    )
    assert len(rows) == 1
    assert rows[0]["an"] == "Alice"
    assert rows[0]["bn"] is None


def test_bb04_null_not_rebound_by_later_match():
    g = Graph()
    g.create_node(["person"], name="A")
    g.create_node(["person"], name="B")
    rows = list(
        cypherast.run(
            "MATCH (a:person {name:'A'}) "
            "OPTIONAL MATCH (a)-[:knows]->(f:person) "
            "MATCH (f) "
            "RETURN a.name AS an, f.name AS fn",
            graph=g,
        )
    )
    assert rows == []


def test_bb05_aggregates_honor_distinct():
    g = Graph()
    g.create_node(["person"], name="A")
    g.create_node(["person"], name="A")
    g.create_node(["person"], name="B")
    rows = list(
        cypherast.run(
            "MATCH (n:person) RETURN count(DISTINCT n.name) AS c, "
            "collect(DISTINCT n.name) AS xs",
            graph=g,
        )
    )
    assert rows[0]["c"] == 2
    assert sorted(rows[0]["xs"]) == ["A", "B"]


def test_bb16_with_aggregation():
    g = _people()
    rows = list(
        cypherast.run(
            "MATCH (n:person) WITH count(n) AS c RETURN c",
            graph=g,
        )
    )
    assert rows[0]["c"] == 2


def test_bb17_order_by_pre_return_vars():
    g = _people()
    rows = list(
        cypherast.run(
            "MATCH (n:person) RETURN n.name AS name ORDER BY n.age",
            graph=g,
        )
    )
    # Bob has age=20, Alice has no age (nulls last ASC) → Bob then Alice
    assert [r["name"] for r in rows] == ["Bob", "Alice"]


def test_bb18_zero_hop_var_length():
    g = _people()
    rows = list(
        cypherast.run(
            "MATCH (a:person {name:'Alice'})-[:knows*0..1]->(x) "
            "RETURN x.name AS xn ORDER BY x.name",
            graph=g,
        )
    )
    names = [r["xn"] for r in rows]
    assert "Alice" in names
    assert "Bob" in names


def test_bb25_create_node_str_label():
    g = Graph()
    n = g.create_node("person", name="x")
    assert n.labels == {"person"}


def test_bb26_nulls_first_last():
    g = Graph()
    g.create_node(["person"], name="A", age=1)
    g.create_node(["person"], name="B")  # age null
    g.create_node(["person"], name="C", age=3)
    first = list(
        cypherast.run(
            "MATCH (n:person) RETURN n.name AS name ORDER BY n.age NULLS FIRST",
            graph=g,
        )
    )
    assert first[0]["name"] == "B"
    last = list(
        cypherast.run(
            "MATCH (n:person) RETURN n.name AS name ORDER BY n.age NULLS LAST",
            graph=g,
        )
    )
    assert last[-1]["name"] == "B"


def test_remove_label_executes():
    g = Graph()
    g.create_node(["Person", "Temp"], name="x")
    cypherast.run("MATCH (n:Person) REMOVE n:Temp RETURN n", graph=g)
    assert g.all_nodes()[0].labels == {"Person"}
