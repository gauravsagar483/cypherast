"""Neutral Cypher core lowering — surface AST → dialect-blind core."""

from __future__ import annotations

import pytest

import cypherast
from cypherast import ast as a
from cypherast.dialects.lower import lower_to_core
from cypherast.errors import ExecuteError
from cypherast.executor import execute
from cypherast.executor.graph import Graph


def test_lower_inline_pattern_where_without_mutating_source() -> None:
    source = cypherast.parse_one(
        "MATCH (n:Person WHERE n.age > 18) RETURN n.name",
        read="neo4j25",
    )
    lowered = lower_to_core(source, dialect="neo4j25")
    assert source.find(a.NodePattern).where is not None
    assert lowered.find(a.NodePattern).where is None
    assert lowered.find(a.Match).where is not None


def test_lower_filter_let_and_for_to_core_clauses() -> None:
    tree = cypherast.parse_one(
        "FOR n IN [1, 2] LET doubled = n * 2 FILTER (n WHERE n > 1) RETURN doubled",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    assert lowered.find(a.For, a.Let, a.Filter) is None
    assert lowered.find(a.Unwind) is not None
    assert lowered.find(a.With) is not None


def test_lower_rejects_filter_item_scoped_to_another_binding() -> None:
    """``WITH * WHERE …`` cannot express a predicate scoped to a different binding."""
    tree = cypherast.parse_one(
        "MATCH (n) MATCH (m) FILTER (n WHERE m.x > 1) RETURN n",
        read="neo4j25",
    )
    with pytest.raises(ExecuteError, match="CG1702") as exc:
        lower_to_core(tree, dialect="neo4j25")
    assert "FILTER" in str(exc.value)


def test_lower_memgraph_bfs_and_reject_weighted_shortest() -> None:
    bfs = cypherast.parse_one(
        "MATCH (a)-[*bfs..3]->(b) RETURN b",
        read="memgraph",
    )
    lowered = lower_to_core(bfs, dialect="memgraph")
    rel = lowered.find(a.RelationshipPattern)
    assert rel.memgraph_quantifier is None
    with pytest.raises(ExecuteError, match="wShortest"):
        lower_to_core(
            cypherast.parse_one(
                "MATCH (a)-[*wShortest (e,n|e.weight)]->(b) RETURN b",
                read="memgraph",
            ),
            dialect="memgraph",
        )


def test_run_neo4j25_inline_where_uses_core_semantics() -> None:
    graph = Graph()
    graph.create_node(["Person"], name="Ada", age=36)
    graph.create_node(["Person"], name="Bob", age=12)
    rows = list(
        cypherast.run(
            "MATCH (n:Person WHERE n.age > 18) RETURN n.name AS name",
            graph=graph,
            read="neo4j25",
        )
    )
    assert rows == [{"name": "Ada"}]


def test_execute_ast_accepts_source_dialect() -> None:
    tree = cypherast.parse_one("FOR n IN [1, 2] RETURN n", read="neo4j25")
    assert list(execute(tree, dialect="neo4j25")) == [{"n": 1}, {"n": 2}]


def test_nested_pattern_where_stays_in_owning_comprehension() -> None:
    tree = cypherast.parse_one(
        "MATCH (n:Person) WHERE size([(n)-[:KNOWS]->(m WHERE m.age > 18) | m]) > 0 RETURN n",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    match = lowered.find(a.Match)
    comprehension = lowered.find(a.PatternComprehension)
    assert isinstance(match.where.this, a.GT)
    assert comprehension.where is not None
    assert comprehension.find(a.NodePattern).where is None


def test_execute_pattern_comprehension_inline_where_filters_matches() -> None:
    graph = Graph()
    ada = graph.create_node(["Person"], name="Ada")
    bob = graph.create_node(["Person"], name="Bob", age=36)
    cyd = graph.create_node(["Person"], name="Cyd", age=12)
    graph.create_rel(ada, bob, "KNOWS")
    graph.create_rel(ada, cyd, "KNOWS")
    tree = cypherast.parse_one(
        "MATCH (n:Person {name: 'Ada'})"
        " RETURN [(n)-[:KNOWS]->(m WHERE m.age > 18) | m.name] AS friends",
        read="neo4j25",
    )
    rows = list(execute(tree, graph=graph, dialect="neo4j25"))
    assert rows == [{"friends": ["Bob"]}]


def test_residual_inline_pattern_where_rejected() -> None:
    tree = cypherast.parse_one(
        "MATCH (n:Person) WHERE (n)-[:KNOWS]->(m:Person WHERE m.age > 18) RETURN n",
        read="neo4j25",
    )
    with pytest.raises(ExecuteError, match="inline pattern WHERE"):
        lower_to_core(tree, dialect="neo4j25")


def test_lower_relationship_inline_where_into_match() -> None:
    tree = cypherast.parse_one(
        "MATCH (a:Person)-[r:KNOWS WHERE r.since > 2020]->(b:Person) RETURN b.name AS name",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    assert lowered.find(a.RelationshipPattern).where is None
    assert lowered.find(a.Match).where is not None


def test_run_relationship_inline_where_filters_rows() -> None:
    graph = Graph()
    ada = graph.create_node(["Person"], name="Ada")
    bob = graph.create_node(["Person"], name="Bob")
    cyd = graph.create_node(["Person"], name="Cyd")
    graph.create_rel(ada, bob, "KNOWS", since=2021)
    graph.create_rel(ada, cyd, "KNOWS", since=2019)
    rows = list(
        cypherast.run(
            "MATCH (a:Person)-[r:KNOWS WHERE r.since > 2020]->(b:Person) RETURN b.name AS name",
            graph=graph,
            read="neo4j25",
        )
    )
    assert rows == [{"name": "Bob"}]


def test_lower_clears_group_by_metadata() -> None:
    tree = cypherast.parse_one(
        "MATCH (n:Person) WITH n.city AS c, count(*) AS total GROUP BY n.city RETURN c",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    assert lowered.find(a.GroupBy) is None
    assert lowered.find(a.With).group_by is None
    assert lowered.find(a.Return).group_by is None


def test_lower_clears_group_by_naming_projection_alias() -> None:
    """``GROUP BY city`` names the alias of the only non-aggregate projection."""
    tree = cypherast.parse_one(
        "MATCH (n:Person) RETURN n.city AS city, count(*) AS c GROUP BY city",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    assert lowered.find(a.GroupBy) is None


def _city_graph() -> Graph:
    graph = Graph()
    graph.create_node(["Person"], name="Ada", city="Paris")
    graph.create_node(["Person"], name="Bob", city="Paris")
    graph.create_node(["Person"], name="Cyd", city="Rome")
    return graph


def test_run_aligned_group_by_aggregates_by_projection_keys() -> None:
    rows = list(
        cypherast.run(
            "MATCH (n:Person) RETURN n.city AS city, count(*) AS c GROUP BY n.city",
            graph=_city_graph(),
            read="neo4j25",
        )
    )
    assert rows == [{"city": "Paris", "c": 2}, {"city": "Rome", "c": 1}]


def test_lower_rejects_group_by_keys_absent_from_projection() -> None:
    """Grouping on a key the clause does not project would silently mis-aggregate."""
    tree = cypherast.parse_one(
        "MATCH (n:Person) RETURN count(*) AS c GROUP BY n.name",
        read="neo4j25",
    )
    with pytest.raises(ExecuteError, match="GROUP BY"):
        lower_to_core(tree, dialect="neo4j25")


def test_run_rejects_group_by_keys_absent_from_projection() -> None:
    with pytest.raises(ExecuteError, match="GROUP BY"):
        cypherast.run(
            "MATCH (n:Person) RETURN count(*) AS c GROUP BY n.name",
            graph=_city_graph(),
            read="neo4j25",
        )


def test_lower_rejects_group_by_missing_a_projection_key() -> None:
    """Projecting two keys while grouping on one changes the aggregate result."""
    tree = cypherast.parse_one(
        "MATCH (n:Person) RETURN n.city AS city, n.name AS name, count(*) AS c GROUP BY n.city",
        read="neo4j25",
    )
    with pytest.raises(ExecuteError, match="GROUP BY"):
        lower_to_core(tree, dialect="neo4j25")


def test_lower_rejects_group_by_beside_star_projection() -> None:
    """``WITH *`` hides the keys, so GROUP BY alignment cannot be established."""
    tree = cypherast.parse_one(
        "MATCH (n:Person) WITH count(*) AS c GROUP BY n.city RETURN c",
        read="neo4j25",
    )
    with_clause = tree.find(a.With)
    with_clause.expressions = [a.Star(), *with_clause.expressions]
    with pytest.raises(ExecuteError, match="GROUP BY"):
        lower_to_core(tree, dialect="neo4j25")


def test_lower_rejects_group_by_without_aggregate_projection() -> None:
    """Grouping with no aggregate collapses duplicate rows; core projection does not."""
    tree = cypherast.parse_one(
        "MATCH (n:Person) RETURN n.city AS city GROUP BY n.city",
        read="neo4j25",
    )
    with pytest.raises(ExecuteError, match="GROUP BY"):
        lower_to_core(tree, dialect="neo4j25")


def test_lower_rejects_inline_where_on_variable_length_relationship() -> None:
    """Hoisting a list-typed relationship predicate would change it to scalar access."""
    tree = cypherast.parse_one(
        "MATCH (a:Person)-[r:KNOWS*1..3 WHERE r.since > 2020]->(b:Person) RETURN b.name AS name",
        read="neo4j25",
    )
    with pytest.raises(ExecuteError, match="variable-length"):
        lower_to_core(tree, dialect="neo4j25")


def test_lower_multi_item_let_expands_to_sequential_with_clauses() -> None:
    tree = cypherast.parse_one(
        "FOR n IN [1, 2] LET a = n * 2, b = a + 1 RETURN b",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    query = lowered.this
    assert isinstance(query, a.Query)
    withs = [c for c in query.clauses if isinstance(c, a.With)]
    assert len(withs) == 2
    assert [w.expressions[1].alias.this for w in withs] == ["a", "b"]
    assert all(w.parent is query for w in withs)


def test_lower_single_item_let_stays_one_with_clause() -> None:
    tree = cypherast.parse_one(
        "FOR n IN [1, 2] LET doubled = n * 2 RETURN doubled",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    assert len([c for c in lowered.this.clauses if isinstance(c, a.With)]) == 1


def test_lower_expands_multi_item_let_inside_nested_query() -> None:
    tree = cypherast.parse_one(
        "CALL { FOR n IN [1, 2] LET a = n * 2, b = a + 1 RETURN b AS b } RETURN b",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    call = lowered.find(a.CallSubquery)
    inner = call.query.this if isinstance(call.query, a.Cypher) else call.query
    withs = [c for c in inner.clauses if isinstance(c, a.With)]
    assert len(withs) == 2
    assert all(w.parent is inner for w in withs)


def test_run_sequential_let_items_see_earlier_item() -> None:
    rows = list(
        cypherast.run(
            "FOR n IN [1, 2] LET a = n * 2, b = a + 1 RETURN b",
            read="neo4j25",
        )
    )
    assert rows == [{"b": 3}, {"b": 5}]


def test_lower_rejects_inline_where_inside_shortest_path() -> None:
    """Shortest-path search semantics must not have predicates hoisted out."""
    tree = cypherast.parse_one(
        "MATCH p = shortestPath((a:Person)-[:KNOWS*]->(b:Person WHERE b.age > 18)) RETURN p",
        read="neo4j25",
    )
    with pytest.raises(ExecuteError, match="inline pattern WHERE"):
        lower_to_core(tree, dialect="neo4j25")


def test_lower_rejects_inline_where_inside_quantified_path() -> None:
    """Quantified path repetition is not a transparent pattern container."""
    inner = a.PathPattern(
        elements=[
            a.NodePattern(
                variable=a.Identifier(this="x"),
                where=a.Where(
                    this=a.GT(
                        this=a.Property(this=a.Identifier(this="x"), name="age"),
                        expression=a.Integer(this=18),
                    )
                ),
            )
        ]
    )
    tree = a.Cypher(
        this=a.Query(
            clauses=[
                a.Match(
                    pattern=a.Pattern(paths=[a.QuantifiedPath(this=inner, min_hops=1, max_hops=3)])
                ),
                a.Return(expressions=[a.Identifier(this="x")]),
            ]
        )
    )
    with pytest.raises(ExecuteError, match="inline pattern WHERE"):
        lower_to_core(tree, dialect="neo4j25")


def test_lower_clears_call_subquery_transaction_metadata() -> None:
    tree = cypherast.parse_one(
        "OPTIONAL CALL (x) { RETURN 1 AS x } IN TRANSACTIONS OF 1000 ROWS RETURN x",
        read="neo4j25",
    )
    lowered = lower_to_core(tree, dialect="neo4j25")
    call = lowered.find(a.CallSubquery)
    assert call.in_transactions is None
    assert call.transaction_rows is None


@pytest.mark.parametrize(
    ("read", "cypher", "surface"),
    [
        (
            "neo4j25",
            "MATCH (n:Person) SEARCH n IN (VECTOR INDEX 'idx' FOR [1.0, 2.0] LIMIT 5) RETURN n",
            "Search",
        ),
        (
            "neo4j5",
            "LOAD CSV WITH HEADERS FROM 'file:///tmp/x.csv' AS row RETURN row",
            "LoadCsv",
        ),
        ("memgraph", "SHOW INDEXES", "AdminStatement"),
        ("neo4j25", "WHEN true THEN { RETURN 1 AS x }", "WhenQuery"),
    ],
)
def test_lower_rejects_unsupported_surfaces(read: str, cypher: str, surface: str) -> None:
    tree = cypherast.parse_one(cypher, read=read)
    with pytest.raises(ExecuteError, match=surface):
        lower_to_core(tree, dialect=read)


def test_run_filter_and_let_core_semantics() -> None:
    rows = list(
        cypherast.run(
            "FOR n IN [1, 2, 3] LET doubled = n * 2 FILTER (n WHERE n > 1) RETURN doubled",
            read="neo4j25",
        )
    )
    assert rows == [{"doubled": 4}, {"doubled": 6}]


def test_run_union_lowers_both_branches() -> None:
    graph = Graph()
    graph.create_node(["Person"], name="Ada", age=36)
    graph.create_node(["Person"], name="Bob", age=12)
    rows = list(
        cypherast.run(
            "MATCH (n:Person WHERE n.age > 30) RETURN n.name AS name"
            " UNION MATCH (m:Person WHERE m.age < 13) RETURN m.name AS name",
            graph=graph,
            read="neo4j25",
        )
    )
    assert rows == [{"name": "Ada"}, {"name": "Bob"}]
