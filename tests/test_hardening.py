"""Hardening: parser edge cases, rename, optimize, translate."""

import cypherast
from cypherast import ast as a


def test_cypher_not_sql_method():
    tree = cypherast.parse_one("MATCH (n) RETURN n")
    assert hasattr(tree, "cypher")
    assert not hasattr(tree, "sql")
    assert "MATCH" in tree.cypher()


def test_optimize_pushdown_eq():
    out = cypherast.optimize(
        "MATCH (n:Person) WHERE n.status = 'ACTIVE' RETURN n"
    ).cypher()
    assert "{status:" in out.replace(" ", "") or "status: 'ACTIVE'" in out or 'status: "ACTIVE"' in out or "status:" in out


def test_translate_roundtrip():
    q = "MATCH (n:Person)-[:KNOWS]->(m) RETURN n.name"
    out = cypherast.translate(q, from_="opencypher", to_="neo4j")
    assert "MATCH" in out
    assert cypherast.transpile(q, from_="opencypher", to_="memgraph")


def test_list_subscript_parse():
    tree = cypherast.parse_one("RETURN split('a.b', '.')[0] AS x")
    assert tree.find(a.ListSubscript)


def test_not_pattern_predicate():
    tree = cypherast.parse_one("MATCH (n) WHERE NOT (n)-[:R]->() RETURN n")
    assert tree.find(a.PatternPredicate)


def test_exists_pattern():
    tree = cypherast.parse_one("MATCH (n) WHERE EXISTS ((n)-[:R]->()) RETURN n")
    assert tree.find(a.PatternPredicate)


def test_call_subquery():
    tree = cypherast.parse_one("MATCH (n) CALL { MATCH (m) RETURN m } RETURN n")
    assert tree.find(a.CallSubquery)


def test_qpp_parse():
    tree = cypherast.parse_one("MATCH ((a)-[:R]->(b)){1,2} RETURN a")
    assert tree.find(a.QuantifiedPath)


def test_foreach_remove_labels():
    tree = cypherast.parse_one(
        "MATCH (n:Person:Temp) FOREACH (x IN [1] | REMOVE n:Temp) RETURN n"
    )
    assert tree.find(a.Foreach)
    assert tree.find(a.Remove)


def test_complex_comprehension():
    tree = cypherast.parse_one(
        "MATCH (n) RETURN [x IN range(1,3) WHERE x > 1 | x] AS xs, "
        "[(n)-[:R]->(m) WHERE m.v > 0 | m.v] AS ys"
    )
    assert tree.find(a.ListComprehension)
    assert tree.find(a.PatternComprehension)


def test_run_string_funcs():
    from cypherast.executor import Graph

    g = Graph()
    g.create_node(["Person"], name="Ada")
    rows = list(
        cypherast.run(
            "MATCH (n:Person) RETURN toLower(n.name) AS n, split(n.name, 'd')[0] AS p",
            graph=g,
        )
    )
    assert rows[0]["n"] == "ada"
    assert rows[0]["p"] == "A"
