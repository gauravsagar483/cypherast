"""Planner / lineage smoke tests."""

import cypherast
from cypherast.executor import Graph


def test_explain():
    text = cypherast.explain("MATCH (n:Person) RETURN n")
    assert "QUERY PLAN" in text
    assert "ScanAll" in text or "Produce" in text


def test_lineage():
    tree = cypherast.parse_one("MATCH (n:Person) RETURN n.name AS name")
    node = cypherast.lineage(tree, binding="name")
    assert node.name == "name"
    assert list(node.walk())


def test_profile():
    g = Graph()
    g.create_node(["Person"], name="Ada")
    text = cypherast.profile("MATCH (n:Person) RETURN n.name AS name", graph=g)
    assert "Rows:" in text
