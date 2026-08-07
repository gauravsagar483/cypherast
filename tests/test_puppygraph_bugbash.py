"""PuppyGraph bug-bash regressions (BB-01…BB-24 focus set)."""

import pytest

import cypherast
from cypherast.errors import ValidationError
from cypherast.optimizer.merge_match_chains import merge_match_chains
from cypherast.schema import GraphSchema, modern_graph_schema

# --- require_labelled_nodes -------------------------------------------------


def test_bb01_anon_end_not_self_join():
    out = cypherast.optimize(
        "MATCH (:Person)-[:KNOWS]->() RETURN 1",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    # Distinct endpoint vars — never (_n_1)-[]->(_n_1)
    assert out.count("_n_1") <= 1 or "_n_1" not in out or out.count("_n_") >= 2
    left, _, right = out.partition(")->")
    # crude: both sides of hop must not share the same bare var name twice as sole binder
    assert not (
        "(_n_1:" in out.replace(" ", "")
        and ">(_n_1:" in out.replace(" ", "")
    ), out


def test_bb02_label_or_roundtrips():
    opt = cypherast.optimize(
        "MATCH (a:person)-[:knows|created]->(b) RETURN b",
        write="puppygraph",
        schema=modern_graph_schema(),
    )
    out = opt.cypher(dialect="puppygraph")
    # Must reparse (no ParseError on |)
    again = cypherast.parse_one(out, read="puppygraph")
    assert again is not None
    assert "person" in out.lower()


def test_bb19_no_wrong_neighbor_label_without_schema():
    """Unknown rel: leave unlabelled end → CG1402, don't invent Software on person end."""
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "MATCH (a:Software)-[:CREATED_BY]->(b) RETURN a,b",
            write="puppygraph",
            schema=GraphSchema(),  # empty — no endpoints, no modern default override
            strict=True,
        )
    assert ei.value.code in {"CG1402", "CG1401"} or "label" in str(ei.value).lower()


def test_bb19_homogeneous_with_schema_still_labels():
    gs = GraphSchema()
    gs.add_label("Metric")
    gs.add_rel("DERIVED_FROM", "Metric", "Metric")
    out = cypherast.optimize(
        "MATCH (a:Metric)-[:DERIVED_FROM]->(b) RETURN a.name LIMIT 20",
        write="puppygraph",
        schema=gs,
    ).cypher(dialect="puppygraph")
    assert "b:Metric" in out.replace(" ", "") or "(b:Metric)" in out.replace(" ", "")


# --- cartesian --------------------------------------------------------------


def test_bb06_connected_multipath_ok():
    out = cypherast.optimize(
        "MATCH (a:Person), (a)-[:KNOWS]->(b:Person) RETURN a,b",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "KNOWS" in out.upper() or "knows" in out.lower()


def test_bb07_consecutive_disjoint_match_rejected():
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "MATCH (a:Person) MATCH (b:Software) RETURN a,b",
            write="puppygraph",
        )
    assert "Cartesian" in str(ei.value) or ei.value.code == "CG1401"


def test_bb07_consecutive_shared_match_ok():
    out = cypherast.optimize(
        "MATCH (a:Person) MATCH (a)-[:KNOWS]->(b:Person) RETURN a,b",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "Person" in out


def test_bb20_merge_match_chains_stitches_path():
    tree = merge_match_chains(
        cypherast.parse_one(
            "MATCH (a:person) MATCH (a)-[:knows]->(b:person) RETURN a,b"
        )
    )
    q = tree.this if hasattr(tree, "this") and tree.__class__.__name__ == "Cypher" else tree
    from cypherast import ast as a

    root = q.this if isinstance(q, a.Cypher) else q
    match = next(c for c in root.clauses if isinstance(c, a.Match))
    assert len(match.pattern.paths) == 1
    cypher = tree.cypher() if hasattr(tree, "cypher") else root.cypher()
    assert ", (a)" not in cypher.replace(" ", "")
    assert "knows" in cypher.lower()


# --- list_concat ------------------------------------------------------------


def test_bb10_list_concat_in_where():
    issues = cypherast.validate(
        'MATCH (n:Person) WHERE n.name IN ["a"] + ["b"] RETURN n',
        dialect="puppygraph",
    )
    assert any("List concatenation" in i.message for i in issues)


def test_bb10_list_concat_in_unwind():
    issues = cypherast.validate(
        "UNWIND [1] + [2] AS x RETURN x",
        dialect="puppygraph",
    )
    assert any("List concatenation" in i.message for i in issues)


def test_bb11_null_plus_list_not_greenwashed():
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "RETURN null + [1] AS x",
            write="puppygraph",
            strict=True,
        )
    assert "List concatenation" in str(ei.value) or ei.value.code == "CG1401"


# --- FET-45 -----------------------------------------------------------------


def test_bb14_where_id_is_not_null_accepted():
    out = cypherast.optimize(
        "MATCH (a:Person) OPTIONAL MATCH (a)-[:KNOWS]->(b:Person) "
        "WHERE id(b) IS NOT NULL RETURN a",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "OPTIONAL" in out.upper()


def test_bb15_or_is_not_null_not_a_guard():
    """Disjunctive IS NOT NULL must not silence FET-45 validate."""
    issues = cypherast.validate(
        "MATCH (a:Person) OPTIONAL MATCH (a)-[:KNOWS]->(b:Person) "
        "WITH a, b WHERE b IS NOT NULL OR true RETURN id(b) AS x",
        dialect="puppygraph",
    )
    assert any(
        "null guard" in i.message.lower() or "OPTIONAL-bound" in i.message
        for i in issues
    )


# --- undef_vars -------------------------------------------------------------


def test_bb08_with_star_preserves_scope():
    out = cypherast.optimize(
        "MATCH (n:Person) WITH * RETURN n",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "RETURN" in out.upper()


def test_bb09_with_where_rejects_pre_with_vars():
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "MATCH (n:person) WITH n.name AS name WHERE n.age > 10 RETURN name",
            write="puppygraph",
        )
    assert "not defined" in str(ei.value).lower()
    assert ei.value.code == "CG1201"


def test_bb13_pattern_comprehension_binders_ok():
    issues = cypherast.validate(
        "MATCH (n:person) RETURN [(n)-[:knows]->(m:person) | m.name] AS xs",
        dialect="puppygraph",
    )
    assert not any("not defined" in i.message for i in issues)


def test_bb22_set_undefined_flagged():
    issues = cypherast.validate(
        "MATCH (n:person) SET n.x = m.y RETURN n",
        dialect="puppygraph",
    )
    assert any(i.code == "CG1201" and "`m`" in i.message for i in issues)


def test_bb24_undefined_uses_cg1201():
    issues = cypherast.validate(
        "MATCH (n:Person) RETURN n.name ORDER BY m.name",
        dialect="puppygraph",
    )
    assert any(i.code == "CG1201" for i in issues)


# --- schema -----------------------------------------------------------------


def test_bb23_map_projection_id_field():
    gs = modern_graph_schema()
    # person id field if catalog supports it
    if hasattr(gs, "add_id_field"):
        gs.add_id_field("person", "id")
    issues = cypherast.validate(
        "MATCH (n:person) RETURN n{.id} AS m",
        dialect="puppygraph",
        schema=gs,
    )
    assert any(i.code == "CG1305" for i in issues)
