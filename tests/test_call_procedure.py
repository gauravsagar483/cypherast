"""Parse / render procedure CALL (openCypher / Neo4j / PuppyGraph / Memgraph)."""

from __future__ import annotations

import cypherast
from cypherast import ast as a


def test_call_subquery_still_works():
    tree = cypherast.parse_one("MATCH (n) CALL { MATCH (m) RETURN m } RETURN n")
    assert tree.find(a.CallSubquery)
    assert tree.find(a.CallProcedure) is None


def test_parse_db_labels():
    tree = cypherast.parse_one("CALL db.labels() YIELD label RETURN label")
    call = tree.find(a.CallProcedure)
    assert call is not None
    assert call.name == "db.labels"
    assert call.expressions == []
    assert call.yield_ is not None
    assert len(call.yield_.expressions) == 1


def test_parse_yield_star():
    tree = cypherast.parse_one("CALL db.labels() YIELD *")
    call = tree.find(a.CallProcedure)
    assert call is not None
    assert isinstance(call.yield_.expressions[0], a.Star)


def test_parse_yield_alias():
    tree = cypherast.parse_one(
        "CALL dbms.components() YIELD name, versions AS vers RETURN name, vers"
    )
    call = tree.find(a.CallProcedure)
    assert call is not None
    assert call.name == "dbms.components"
    exprs = call.yield_.expressions
    assert isinstance(exprs[0], a.Identifier)
    assert isinstance(exprs[1], a.Alias)


def test_parse_puppygraph_pagerank_map_arg():
    q = """
    CALL algo.paral.pagerank({
        labels: ['Page'],
        relationshipTypes: ['LINKS'],
        maxIterations: 20,
        dampingFactor: 0.85
    }) YIELD id, score
    RETURN id, score
    """
    tree = cypherast.parse_one(q)
    call = tree.find(a.CallProcedure)
    assert call is not None
    assert call.name == "algo.paral.pagerank"
    assert len(call.expressions) == 1
    assert isinstance(call.expressions[0], a.Map)
    rendered = tree.cypher()
    tree2 = cypherast.parse_one(rendered)
    assert tree2.find(a.CallProcedure).name == "algo.paral.pagerank"


def test_parse_wcc_and_lpa():
    for name in ("algo.wcc", "algo.labelPropagation"):
        q = f"CALL {name}({{labels: ['User'], relationshipTypes: ['LINK']}}) YIELD id RETURN id"
        tree = cypherast.parse_one(q)
        assert tree.find(a.CallProcedure).name == name


def test_parse_optional_where_after_yield():
    tree = cypherast.parse_one(
        "CALL db.labels() YIELD label WHERE label STARTS WITH 'P' RETURN label"
    )
    call = tree.find(a.CallProcedure)
    assert call is not None
    assert call.where is not None


def test_parse_standalone_no_yield():
    tree = cypherast.parse_one("CALL db.ping()")
    call = tree.find(a.CallProcedure)
    assert call is not None
    assert call.yield_ is None
    assert "CALL db.ping()" in tree.cypher()


def test_roundtrip_memgraph_style():
    q = "CALL module.procedure(42) YIELD result AS procedure_result RETURN procedure_result"
    out = cypherast.parse_one(q).cypher()
    again = cypherast.parse_one(out).cypher()
    assert again == out


def test_optimize_puppygraph_pass_through():
    q = (
        "CALL algo.wcc({labels: ['Metric'], relationshipTypes: ['BELONGS_TO_DOMAIN']}) "
        "YIELD id, componentId RETURN id, componentId"
    )
    tree = cypherast.optimize(q, write="puppygraph", schema=None, strict=False)
    call = tree.find(a.CallProcedure)
    assert call is not None
    assert call.name == "algo.wcc"
    assert "componentId" in tree.cypher()


def test_optimize_puppygraph_algo_strict_true():
    """YIELD bindings in scope; map args must not crash CG1201 (_refs expects AstNode)."""
    queries = [
        (
            "CALL algo.paral.pagerank({labels: ['Metric'], relationshipTypes: ['BELONGS_TO_DOMAIN'], "
            "maxIterations: 5, dampingFactor: 0.85}) YIELD id, score RETURN id, score"
        ),
        (
            "CALL algo.wcc({labels: ['Metric'], relationshipTypes: ['BELONGS_TO_DOMAIN']}) "
            "YIELD id, componentId RETURN id, componentId"
        ),
        (
            "CALL algo.labelPropagation({labels: ['Metric'], relationshipTypes: ['BELONGS_TO_DOMAIN']}) "
            "YIELD id, communityId RETURN id, communityId"
        ),
        (
            "CALL algo.connectedComponentFinding({labels: ['Metric'], "
            "relationshipTypes: ['BELONGS_TO_DOMAIN']}) YIELD id, componentId RETURN id, componentId"
        ),
    ]
    for q in queries:
        tree = cypherast.optimize(q, write="puppygraph", schema=None, strict=True)
        assert tree.find(a.CallProcedure) is not None
        assert "YIELD" in tree.cypher()
