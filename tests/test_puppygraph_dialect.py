"""PuppyGraph dialect capabilities: optimize + translate to/from."""

import cypherast
from cypherast.dialects.puppygraph import PuppyGraph


def test_capabilities_flags():
    caps = PuppyGraph.capabilities
    assert caps.require_labelled_nodes
    assert not caps.allow_cartesian_match_paths
    assert caps.max_var_length_hops is None
    assert caps.allow_unbounded_var_length
    assert not caps.allow_exists_function
    assert not caps.allow_list_comprehension
    assert caps.max_collect_distinct_per_clause == 1
    assert not caps.allow_distinct_with_aggregate
    assert caps.require_limit_on_row_return


def test_optimize_injects_limit():
    out = cypherast.optimize(
        "MATCH (n:Person) RETURN n.name",
        read="opencypher",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "LIMIT" in out.upper()
    assert "Person" in out


def test_optimize_pure_aggregate_may_omit_limit():
    out = cypherast.optimize(
        "MATCH (n:Person) RETURN count(n) AS c",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    # count-only → LIMIT optional; rewrite should not force one
    assert "count" in out.lower()


def test_optimize_splits_cartesian_match():
    out = cypherast.optimize(
        "MATCH (a:Person), (b:Person) RETURN a, b LIMIT 10",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    # Must not keep comma paths in one MATCH
    assert ", (b" not in out.replace(" ", "")
    assert out.upper().count("MATCH") >= 2


def test_optimize_caps_collect_distinct():
    out = cypherast.optimize(
        "MATCH (a:Person)-[:R]->(b:Item) "
        "RETURN collect(DISTINCT a.name) AS as_, collect(DISTINCT b.name) AS bs LIMIT 10",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    # Second collect(DISTINCT) → count(DISTINCT)
    assert out.lower().count("collect(distinct") <= 1
    assert "count" in out.lower()


def test_optimize_drops_distinct_with_agg():
    out = cypherast.optimize(
        "MATCH (a:Person)-[:R]->(b:Item) "
        "RETURN DISTINCT a.name AS n, count(b) AS c LIMIT 10",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "DISTINCT" not in out.upper().split("RETURN")[-1].split("LIMIT")[0] or (
        "DISTINCT" not in out.upper()
    )


def test_pattern_predicate_no_exists_on_puppygraph():
    out = cypherast.translate(
        "MATCH (n:Person) WHERE NOT (n)-[:R]->(:Item) RETURN n LIMIT 10",
        from_="opencypher",
        to_="puppygraph",
        optimize=True,
    )
    assert "EXISTS" not in out.upper()
    assert "NOT" in out.upper()


def test_translate_to_and_from_puppygraph():
    q = "MATCH (a:Person)-[:KNOWS*1..3]->(b:Person) WHERE a.status = 'ACTIVE' RETURN a.name LIMIT 20"
    to_pg = cypherast.translate(q, from_="opencypher", to_="puppygraph", optimize=True)
    assert "ACTIVE" in to_pg or "{status" in to_pg.replace(" ", "")
    assert "LIMIT" in to_pg.upper()

    back = cypherast.translate(to_pg, from_="puppygraph", to_="opencypher", optimize=True)
    assert "MATCH" in back
    # round-trip parseable
    cypherast.parse_one(back, read="opencypher")
    cypherast.parse_one(to_pg, read="puppygraph")


def test_validate_list_comprehension():
    issues = cypherast.validate(
        "MATCH (n:Person) RETURN [x IN [1,2] | x] AS xs LIMIT 5",
        dialect="puppygraph",
    )
    assert any("List comprehension" in i.message for i in issues)


def test_validate_unlabelled_match():
    issues = cypherast.validate(
        "MATCH (n) RETURN n LIMIT 5",
        dialect="puppygraph",
    )
    assert any(i.code == "CG1402" or "Unlabelled" in i.message for i in issues)


def test_validate_bound_reuse_unlabelled_ok():
    """Bare (a) after labelled bind is not CG1402 (OPTIONAL MATCH / chain)."""
    issues = cypherast.validate(
        "MATCH (a:person) OPTIONAL MATCH (a)-[:knows]->(b:person) RETURN a.name, b.name LIMIT 20",
        dialect="puppygraph",
    )
    assert not any(i.code == "CG1402" for i in issues)


def test_validate_new_unlabelled_endpoint_still_fails():
    issues = cypherast.validate(
        "MATCH (a:person)-[:knows|created]->(b) RETURN a.name LIMIT 20",
        dialect="puppygraph",
    )
    assert any(i.code == "CG1402" and "(b)" in i.message for i in issues)


def test_optimize_labels_anonymous_endpoints():
    """PuppyGraph optimize fills () from default schema — no CG1402 after."""
    opt = cypherast.optimize(
        "MATCH ()-[e:knows]->() RETURN e LIMIT 20",
        write="puppygraph",
    )
    out = opt.cypher(dialect="puppygraph")
    assert "()" not in out.replace(" ", "")
    assert ":person" in out.lower()
    assert "knows" in out.lower()
    issues = cypherast.validate(opt, dialect="puppygraph")
    assert not any(i.code == "CG1402" for i in issues)


def test_optimize_labels_multi_rel_end():
    """knows|created → end gets :person|software from schema."""
    opt = cypherast.optimize(
        "MATCH (a:person)-[:knows|created]->(b) RETURN a.name, labels(b) AS labs LIMIT 20",
        write="puppygraph",
    )
    out = opt.cypher(dialect="puppygraph")
    assert "person|software" in out.lower() or (":person" in out.lower() and "software" in out.lower())
    issues = cypherast.validate(opt, dialect="puppygraph")
    assert not any(i.code == "CG1402" for i in issues)


def test_positive_pattern_pred_optimize_puppygraph():
    out = cypherast.optimize(
        "MATCH (n:person) WHERE (n)-[:created]->(:software) RETURN n.name LIMIT 20",
        read="puppygraph",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "EXISTS" not in out.upper()
    assert "WHERE" in out.upper()
    assert "created" in out.lower()


def test_optimize_opencypher_unchanged_caps():
    # openCypher write should not force LIMIT
    out = cypherast.optimize(
        "MATCH (n:Person) RETURN n.name",
        write="opencypher",
    ).cypher()
    assert "LIMIT" not in out.upper()
