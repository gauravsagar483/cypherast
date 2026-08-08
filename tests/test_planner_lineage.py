"""Planner / lineage smoke tests."""

import pytest

import cypherast
from cypherast import ast as a
from cypherast.executor import Graph
from cypherast.planner import explain as planner_explain
from cypherast.planner import plan_query
from cypherast.planner import profile as planner_profile


def test_explain():
    text = cypherast.explain("MATCH (n:Person) RETURN n", read="opencypher")
    assert "QUERY PLAN" in text
    assert "ScanAll" in text or "Produce" in text


def test_explain_neo4j25_inline_where_shows_filter() -> None:
    """Inline pattern WHERE must be lowered so the plan includes Filter."""
    text = cypherast.explain(
        "MATCH (n:Person WHERE n.age > 18) RETURN n",
        read="neo4j25",
    )
    assert "QUERY PLAN" in text
    assert "Filter" in text


def test_planner_explain_lowers_surface_ast_with_or_without_dialect() -> None:
    """Neutral core is structural: planning lowers even when no dialect is named."""
    tree = cypherast.parse_one(
        "MATCH (n:Person WHERE n.age > 18) RETURN n",
        read="neo4j25",
    )
    assert "Filter" in planner_explain(tree, dialect="neo4j25")
    assert "Filter" in planner_explain(tree, dialect=None)
    plan = plan_query(tree, cost=False, dialect="neo4j25")
    assert "Filter" in str(plan)
    assert "Filter" in str(plan_query(tree, cost=False, dialect=None))


def test_planner_lowering_leaves_source_tree_unchanged() -> None:
    tree = cypherast.parse_one(
        "MATCH (n:Person WHERE n.age > 18) RETURN n",
        read="neo4j25",
    )
    planner_explain(tree, dialect=None)
    assert tree.find(a.NodePattern).where is not None


def test_lineage():
    tree = cypherast.parse_one("MATCH (n:Person) RETURN n.name AS name", read="opencypher")
    node = cypherast.lineage(tree, binding="name", from_="opencypher")
    assert node.name == "name"
    assert list(node.walk())
    # Second call must still hit the public function (not the submodule).
    again = cypherast.lineage(tree, binding="name", from_="opencypher")
    assert again.name == "name"
    assert callable(cypherast.lineage)


def test_lineage_lowers_neo4j25_let() -> None:
    """LET must lower to WITH so provenance reaches the defining property."""
    node = cypherast.lineage(
        "MATCH (n:Person) LET age = n.age RETURN age",
        binding="age",
        from_="neo4j25",
    )
    assert node.name == "age"
    props = [
        n.expression
        for n in node.walk()
        if isinstance(n.expression, a.Property)
    ]
    assert any(p.cypher() == "n.age" for p in props), (
        f"expected n.age provenance after LET→WITH lower; got {[p.cypher() for p in props]!r} "
        f"walk={[n.expression.cypher() for n in node.walk()]!r}"
    )


def test_lineage_self_aliasing_with_terminates() -> None:
    """``WITH n AS n`` must not recurse forever and must keep useful provenance."""
    node = cypherast.lineage(
        "MATCH (n:Person) WITH n AS n RETURN n",
        binding="n",
        from_="opencypher",
    )
    assert node.name == "n"
    assert isinstance(node.expression, a.Identifier)
    assert node.expression.this == "n"


def test_lineage_alias_cycle_terminates() -> None:
    """Mutually renaming WITH aliases must terminate instead of cycling."""
    node = cypherast.lineage(
        "MATCH (n:Person) WITH n AS m WITH m AS n RETURN n",
        binding="n",
        from_="opencypher",
    )
    assert node.name == "n"


def test_lineage_resolves_nearest_preceding_with_definition() -> None:
    """A later WITH shadows an earlier alias of the same name."""
    node = cypherast.lineage(
        "MATCH (p:Person) WITH p.a AS x WITH p.b AS x RETURN x",
        binding="x",
        from_="opencypher",
    )
    assert node.expression.cypher() == "p.b"


def test_lineage_ignores_with_after_return() -> None:
    """Definitions must be searched only among clauses preceding the RETURN."""
    tree = a.Cypher(
        this=a.Query(
            clauses=[
                a.With(
                    expressions=[
                        a.Alias(
                            this=a.Property(this=a.Identifier(this="p"), name="a"),
                            alias=a.Identifier(this="x"),
                        )
                    ]
                ),
                a.Return(expressions=[a.Identifier(this="x")]),
                a.With(
                    expressions=[
                        a.Alias(
                            this=a.Property(this=a.Identifier(this="p"), name="b"),
                            alias=a.Identifier(this="x"),
                        )
                    ]
                ),
            ]
        )
    )
    node = cypherast.lineage(tree, binding="x", from_="opencypher")
    assert node.expression.cypher() == "p.a"


def test_profile():
    g = Graph()
    g.create_node(["Person"], name="Ada")
    text = cypherast.profile(
        "MATCH (n:Person) RETURN n.name AS name",
        graph=g,
        read="opencypher",
    )
    assert "Rows:" in text


def test_profile_neo4j25_inline_where_counts_filtered_rows() -> None:
    graph = Graph()
    graph.create_node(["Person"], age=36)
    graph.create_node(["Person"], age=12)
    text = cypherast.profile(
        "MATCH (n:Person WHERE n.age > 18) RETURN n",
        graph=graph,
        read="neo4j25",
    )
    assert "Rows: 1" in text
    assert "Filter" in text


def test_profile_rejects_invalid_graph() -> None:
    with pytest.raises(TypeError, match="graph must be a cypherast.executor.Graph"):
        cypherast.profile("RETURN 1", graph=object(), read="opencypher")


def test_planner_profile_dialect_lowers_and_filters_rows() -> None:
    graph = Graph()
    graph.create_node(["Person"], age=36)
    graph.create_node(["Person"], age=12)
    tree = cypherast.parse_one(
        "MATCH (n:Person WHERE n.age > 18) RETURN n",
        read="neo4j25",
    )
    text = planner_profile(tree, graph=graph, dialect="neo4j25")
    assert "Rows: 1" in text
    assert "Filter" in text
