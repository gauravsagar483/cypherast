"""PuppyGraph dialect capabilities: optimize + translate to/from."""

import pytest

import cypherast
from cypherast.dialects.puppygraph import PuppyGraph
from cypherast.errors import ValidationError
from cypherast.schema import GraphSchema


def test_capabilities_flags():
    caps = PuppyGraph.capabilities
    assert caps.reject_excluded_clauses
    assert caps.check_function_signatures
    assert caps.reject_undirected_patterns
    assert not caps.reject_var_length_binding
    assert caps.reject_call_subquery
    assert caps.reject_gql_nodes
    assert caps.reject_quantified_path
    assert caps.require_labelled_nodes
    assert not caps.allow_cartesian_match_paths
    assert caps.max_var_length_hops is None
    assert caps.allow_unbounded_var_length
    assert not caps.rewrite_var_length_bounds
    assert not caps.allow_exists_function
    assert not caps.allow_list_comprehension
    assert caps.max_collect_distinct_per_clause == 1
    assert not caps.rewrite_collect_distinct_cap
    assert not caps.allow_collect_distinct_with_other_aggregates
    assert not caps.allow_distinct_with_aggregate
    assert caps.require_matching_union_columns
    assert caps.check_undefined_variables
    assert not caps.allow_id_in_string_predicates
    assert not caps.allow_unguarded_optional_scalar_use
    assert caps.rewrite_unguarded_optional_scalar_use
    assert not caps.rewrite_cartesian_match_paths
    assert not caps.rewrite_distinct_beside_aggregate


def test_validate_bound_var_length_rel_ok():
    """PuppyGraph allows bound var-length rels (OC9 CG1504 does not)."""
    for q in (
        "MATCH ()-[r*1..2]->() RETURN r LIMIT 20",
        "MATCH (affected:Metric)-[_r_3:DERIVED_FROM*0..3]->(anchor:Metric) "
        "RETURN DISTINCT affected.name AS affected_metric LIMIT 20",
    ):
        issues = cypherast.validate(q, dialect="puppygraph")
        assert not any(i.code == "CG1504" for i in issues)
        opt = cypherast.optimize(q, write="puppygraph")
        assert not any(i.code == "CG1504" for i in cypherast.validate(opt, dialect="puppygraph"))


def test_first_last_as_identifiers_and_nulls_order():
    """P1: FIRST/LAST/NULLS are not global keywords."""
    q = "MATCH (n:person) RETURN n.first AS first ORDER BY n.last NULLS LAST LIMIT 20"
    tree = cypherast.parse_one(q, read="puppygraph")
    assert "n.first" in tree.cypher()
    out = cypherast.optimize(q, write="puppygraph").cypher(dialect="puppygraph")
    assert "NULLS" not in out.upper()
    assert "first" in out.lower()


def test_create_return_in_scope():
    """P2: CREATE binders are in scope for RETURN."""
    opt = cypherast.optimize(
        "CREATE (n:person {name: 'x'}) RETURN n",
        write="puppygraph",
    )
    assert "CREATE" in opt.cypher(dialect="puppygraph").upper()


def test_pattern_pred_reuse_ok_new_binder_rejected():
    """P3: outer reuse OK; new binder in WHERE pattern rejected."""
    ok = cypherast.optimize(
        "MATCH (n:person) WHERE (n)-[:knows]->(:person) RETURN n LIMIT 20",
        write="puppygraph",
    )
    assert "WHERE" in ok.cypher(dialect="puppygraph").upper()
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "MATCH (n:person) WHERE (n)-[:knows]->(m:person) RETURN n LIMIT 20",
            write="puppygraph",
        )
    assert "new variables" in str(ei.value).lower() or "Pattern predicates" in str(ei.value)


def test_list_concat_alias_and_not_subscript():
    """P4: collect aliases flagged; split()[0] + string not list-concat."""
    bad = cypherast.validate(
        "MATCH (m:Metric) WITH collect(m.name) AS a, collect(m.name) AS b RETURN a + b LIMIT 20",
        dialect="puppygraph",
    )
    assert any("List concatenation" in i.message for i in bad)
    ok = cypherast.validate(
        "MATCH (m:Metric) RETURN split(m.name, '_')[0] + '_x' AS x LIMIT 20",
        dialect="puppygraph",
    )
    assert not any("List concatenation" in i.message for i in ok)


def test_optimize_does_not_inject_limit():
    out = cypherast.optimize(
        "MATCH (n:Person) RETURN n.name",
        read="opencypher",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "LIMIT" not in out.upper()
    assert "Person" in out


def test_order_by_scope_after_with():
    """ORDER BY after WITH may only use projected aliases."""
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "MATCH (n:Metric) WITH count(n) AS c RETURN c ORDER BY n.name",
            write="puppygraph",
        )
    assert "not defined" in str(ei.value).lower()
    assert ei.value.code == "CG1201"


def test_optimize_pure_aggregate_ok_without_limit():
    out = cypherast.optimize(
        "MATCH (n:Person) RETURN count(n) AS c",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "count" in out.lower()
    assert "LIMIT" not in out.upper()


def test_optimize_splits_cartesian_match():
    """Cartesian comma MATCH: optimize raises — do not greenwash with split."""
    q = "MATCH (a:Person), (b:Person) RETURN a, b LIMIT 10"
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(q, write="puppygraph")
    assert ei.value.code in {"CG1401", "CG1402"} or "Cartesian" in str(ei.value)
    # Soft path still leaves comma MATCH (rewrite disabled)
    soft = cypherast.optimize(q, write="puppygraph", strict=False)
    out = soft.cypher(dialect="puppygraph")
    assert out.upper().count("MATCH") == 1
    issues = cypherast.validate(soft, dialect="puppygraph")
    assert any("Cartesian" in i.message or "Multiple paths" in i.message for i in issues)


def test_optimize_caps_collect_distinct():
    """APT-18: multi collect(DISTINCT) → optimize raises CG1401 (no TE-14 rewrite)."""
    q = (
        "MATCH (a:Person)-[:R]->(b:Item) "
        "RETURN collect(DISTINCT a.name) AS as_, collect(DISTINCT b.name) AS bs LIMIT 10"
    )
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(q, write="puppygraph")
    assert "collect" in str(ei.value).lower()
    soft = cypherast.optimize(q, write="puppygraph", strict=False)
    assert soft.cypher(dialect="puppygraph").lower().count("collect(distinct") >= 2


def test_optimize_drops_distinct_with_agg():
    """PJT-97: DISTINCT beside agg — optimize raises (no silent DISTINCT drop)."""
    q = "MATCH (a:Person)-[:R]->(b:Item) RETURN DISTINCT a.name AS n, count(b) AS c LIMIT 10"
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(q, write="puppygraph")
    assert "DISTINCT" in str(ei.value).upper() or "aggregate" in str(ei.value).lower()
    soft = cypherast.optimize(q, write="puppygraph", strict=False)
    assert "DISTINCT" in soft.cypher(dialect="puppygraph").upper()


def test_mixed_aggregate_projection_rejected():
    """Engine AggregationMixingCheck: a grouping key may not sit inside an aggregate expression."""
    q = (
        "MATCH (exp:Experiment{state_name: 'ACTIVE'})-[:TRACKS_METRIC]->(m:Metric) "
        "WITH count(DISTINCT exp) AS used "
        "MATCH (exp2:Experiment{state_name: 'ACTIVE'}) "
        "RETURN used, count(DISTINCT exp2) AS total, "
        "toFloat(used) / toFloat(count(DISTINCT exp2)) * 100.0 AS pct LIMIT 20"
    )
    issues = cypherast.validate(q, dialect="puppygraph")
    assert any(i.code == "CG1401" and "Aggregate mixed" in i.message for i in issues)
    with pytest.raises(ValidationError):
        cypherast.optimize(q, write="puppygraph")


def test_mixed_aggregate_projection_split_with_ok():
    """Aggregating in its own WITH first, then combining aliases, passes."""
    q = (
        "MATCH (exp:Experiment{state_name: 'ACTIVE'})-[:TRACKS_METRIC]->(m:Metric) "
        "WITH count(DISTINCT exp) AS used "
        "MATCH (exp2:Experiment{state_name: 'ACTIVE'}) "
        "WITH used, count(DISTINCT exp2) AS total "
        "RETURN used, total, toFloat(used) / toFloat(total) * 100.0 AS pct LIMIT 20"
    )
    assert not any(
        "Aggregate mixed" in i.message for i in cypherast.validate(q, dialect="puppygraph")
    )


def test_aggregate_arithmetic_beside_grouping_key_ok():
    """Arithmetic over aggregates alone is fine; keys count only as standalone items."""
    for q in (
        "MATCH (m:Metric) RETURN count(*) + 1 AS x LIMIT 20",
        "MATCH (m:Metric) RETURN m.status AS s, count(*) * 2 AS x LIMIT 20",
    ):
        assert not any(
            "Aggregate mixed" in i.message for i in cypherast.validate(q, dialect="puppygraph")
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


def test_optimize_propagates_label_without_schema_rel():
    """With schema endpoints, unlabelled end is filled (no neighbor-copy hack)."""
    gs = GraphSchema()
    gs.add_label("Metric")
    gs.add_rel("DERIVED_FROM", "Metric", "Metric")
    opt = cypherast.optimize(
        "MATCH (a:Metric)-[:DERIVED_FROM]->(b) RETURN a.name LIMIT 20",
        write="puppygraph",
        schema=gs,
    )
    out = opt.cypher(dialect="puppygraph")
    assert ":Metric" in out
    assert "(b:Metric)" in out.replace(" ", "") or "b:Metric" in out
    assert not any(i.code == "CG1402" for i in cypherast.validate(opt, dialect="puppygraph"))


def test_optimize_labels_anonymous_end_from_neighbor():
    gs = GraphSchema()
    gs.add_label("Metric")
    gs.add_rel("COMPUTED_FROM", "Metric", "Metric")
    opt = cypherast.optimize(
        "MATCH (m:Metric)-[:COMPUTED_FROM]->() RETURN m LIMIT 20",
        write="puppygraph",
        schema=gs,
    )
    out = opt.cypher(dialect="puppygraph")
    assert "()" not in out.replace(" ", "")
    assert "Metric" in out
    assert not any(i.code == "CG1402" for i in cypherast.validate(opt, dialect="puppygraph"))


def test_optimize_prior_bound_label_not_neighbor_copy():
    """Reuse site (cat) must keep Catalog — not copy Check from end."""
    q = (
        "MATCH (cat:Catalog) "
        "OPTIONAL MATCH (cat)-[:HAS_CHECK]->(chk:Check) "
        "RETURN CASE WHEN chk IS NULL THEN NULL ELSE "
        "replace(split(toString(id(chk)), '[')[1], ']', '') END AS check_vertex_id"
    )
    opt = cypherast.optimize(q, write="puppygraph")
    out = opt.cypher(dialect="puppygraph")
    assert "cat:Check" not in out.replace(" ", "")
    assert "Catalog" in out
    assert "Check" in out
    # OPTIONAL reuse of cat should carry prior label (or stay bare — never wrong label)
    assert "(cat:Catalog)" in out.replace(" ", "") or "(cat)-" in out.replace(" ", "")
    assert not any(i.code == "CG1402" for i in cypherast.validate(opt, dialect="puppygraph"))


def test_optimize_labels_anonymous_endpoints():
    """No schema → residual :_Node on bare ends (not domain invent)."""
    opt = cypherast.optimize(
        "MATCH ()-[e:knows]->() RETURN e LIMIT 20",
        write="puppygraph",
    )
    out = opt.cypher(dialect="puppygraph")
    assert "()" not in out.replace(" ", "")
    assert ":_Node" in out or "_Node" in out
    assert "knows" in out.lower()
    issues = cypherast.validate(opt, dialect="puppygraph")
    assert not any(i.code == "CG1402" for i in issues)


def test_optimize_labels_multi_rel_end():
    """knows|created → end gets :person|software when schema has endpoints."""
    gs = GraphSchema()
    gs.add_label("person")
    gs.add_label("software")
    gs.add_rel("knows", "person", "person")
    gs.add_rel("created", "person", "software")
    opt = cypherast.optimize(
        "MATCH (a:person)-[:knows|created]->(b) RETURN a.name, labels(b) AS labs LIMIT 20",
        write="puppygraph",
        schema=gs,
    )
    out = opt.cypher(dialect="puppygraph")
    assert "person|software" in out.lower() or (
        ":person" in out.lower() and "software" in out.lower()
    )
    issues = cypherast.validate(opt, dialect="puppygraph")
    assert not any(i.code == "CG1402" for i in issues)


def test_optimize_bare_residual_node():
    """Bare MATCH (n) → (n:_Node); no CG1402 after optimize."""
    opt = cypherast.optimize("MATCH (n) RETURN n", write="puppygraph")
    out = opt.cypher(dialect="puppygraph")
    assert "n:_Node" in out.replace(" ", "")
    assert not any(i.code == "CG1402" for i in cypherast.validate(opt, dialect="puppygraph"))


def test_call_subquery_rejected_by_oc9():
    """OC9 (and PuppyGraph) reject CALL { … } subqueries."""
    q = (
        "MATCH (p:Person) CALL { MATCH (a:Animal) RETURN a.name AS animal_name } "
        "RETURN p.name AS person_name, animal_name"
    )
    issues = cypherast.validate(q, dialect="puppygraph")
    assert any(i.code == "CG1505" for i in issues)
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(q, write="puppygraph")
    assert ei.value.code == "CG1505"


def test_optimize_mines_labels_from_lineage_query():
    """Mine COMPUTED_FROM Metric→Measure, then label later unlabelled end."""
    q = (
        "MATCH (m:Metric)-[:COMPUTED_FROM]->(ms:Measure) "
        "WITH m "
        "MATCH (m)-[:COMPUTED_FROM]->() "
        "RETURN m LIMIT 20"
    )
    opt = cypherast.optimize(q, write="puppygraph")
    out = opt.cypher(dialect="puppygraph")
    assert "Measure" in out
    assert "()" not in out.replace(" ", "")
    assert not any(i.code == "CG1402" for i in cypherast.validate(opt, dialect="puppygraph"))


def test_optimize_metric_with_reuse_ok():
    q = "MATCH (m:Metric) WITH m MATCH (m)-[:COMPUTED_FROM]->(ms:Measure) RETURN m, ms LIMIT 20"
    opt = cypherast.optimize(q, write="puppygraph")
    assert not any(i.code == "CG1402" for i in cypherast.validate(opt, dialect="puppygraph"))
    assert "Metric" in opt.cypher(dialect="puppygraph")


def test_validate_list_concat_and_node_in_list():
    issues = cypherast.validate(
        "MATCH (n:person) RETURN collect(n.name) + ['x'] AS xs LIMIT 5",
        dialect="puppygraph",
    )
    assert any("List concatenation" in i.message for i in issues)
    issues2 = cypherast.validate(
        "MATCH (n:person) WHERE n IN [n] RETURN n LIMIT 5",
        dialect="puppygraph",
    )
    assert any("Node IN list" in i.message for i in issues2)


def test_harness_reject_apt18_et06_union_id_scope_varlen():
    """Bad-query harness: optimize raises (expected=fail); soft+validate still flags."""

    def must_raise(q: str, *needles: str) -> None:
        with pytest.raises(ValidationError) as ei:
            cypherast.optimize(q, write="puppygraph")
        blob = str(ei.value).lower()
        assert any(n.lower() in blob for n in needles)

    def soft_issues(q: str) -> list:
        opt = cypherast.optimize(q, write="puppygraph", strict=False)
        return cypherast.validate(opt, dialect="puppygraph")

    must_raise(
        "MATCH (m:Metric) WITH collect(DISTINCT m) AS metrics, "
        "collect(DISTINCT m.name) AS names RETURN size(metrics)",
        "collect",
    )
    apt18 = soft_issues(
        "MATCH (m:Metric) WITH collect(DISTINCT m) AS metrics, "
        "collect(DISTINCT m.name) AS names RETURN size(metrics)"
    )
    assert any("At most 1 collect" in i.message or "collect(DISTINCT" in i.message for i in apt18)

    must_raise(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) + [m.name] AS names RETURN names LIMIT 20",
        "concat",
        "List concatenation",
    )
    et06 = soft_issues(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) + [m.name] AS names RETURN names LIMIT 20"
    )
    assert any("List concatenation" in i.message for i in et06)

    et06a = soft_issues(
        "MATCH (m:Metric)-[:DERIVED_FROM]->(base:Metric) WITH m, collect(base.name) AS bases "
        "RETURN m.name AS metric, bases + ['x'] AS combined LIMIT 20"
    )
    assert any("List concatenation" in i.message for i in et06a)
    must_raise(
        "MATCH (m:Metric)-[:DERIVED_FROM]->(base:Metric) WITH m, collect(base.name) AS bases "
        "RETURN m.name AS metric, bases + ['x'] AS combined LIMIT 20",
        "concat",
        "List concatenation",
    )

    et21 = soft_issues(
        "MATCH (m:Metric)-[:DERIVED_FROM]->(base:Metric) WITH collect(base) AS bases "
        "MATCH (x:Metric)-[:DERIVED_FROM]->(y:Metric) WHERE y IN bases RETURN x.name LIMIT 20"
    )
    assert any("Node IN list" in i.message for i in et21)
    must_raise(
        "MATCH (m:Metric)-[:DERIVED_FROM]->(base:Metric) WITH collect(base) AS bases "
        "MATCH (x:Metric)-[:DERIVED_FROM]->(y:Metric) WHERE y IN bases RETURN x.name LIMIT 20",
        "Node IN list",
    )

    union = soft_issues(
        "MATCH (m:Metric) RETURN m.name AS metric_name "
        "UNION MATCH (ms:Measure) RETURN ms.name AS measure_name"
    )
    assert any("UNION" in i.message for i in union)
    must_raise(
        "MATCH (m:Metric) RETURN m.name AS metric_name "
        "UNION MATCH (ms:Measure) RETURN ms.name AS measure_name",
        "UNION",
    )

    idc = soft_issues("MATCH (m:Metric) WHERE id(m) CONTAINS 'vertex' RETURN m.name LIMIT 20")
    assert any("id()" in i.message or "elementId" in i.message for i in idc)
    must_raise(
        "MATCH (m:Metric) WHERE id(m) CONTAINS 'vertex' RETURN m.name LIMIT 20",
        "id()",
        "elementId",
    )

    # Scope (CG1201): ELSE [m.name] after WITH drops m — also ET-17 list vs list_lit
    et17_scope = soft_issues(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) AS items "
        "RETURN CASE WHEN size(items) > 0 THEN items ELSE [m.name] END"
    )
    assert any("not defined" in i.message for i in et17_scope)
    assert any("CASE" in i.message for i in et17_scope)
    must_raise(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) AS items "
        "RETURN CASE WHEN size(items) > 0 THEN items ELSE [m.name] END",
        "CASE",
        "not defined",
        "list",
    )

    # ET-17: collect-list vs literal list / map (fail-closed; PuppyGraph runtime)
    et17_list = soft_issues(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) AS items "
        "RETURN CASE WHEN size(items) > 0 THEN items ELSE ['x'] END LIMIT 20"
    )
    assert any(
        "Case" in i.message or "CASE" in i.message or "ET-17" in (i.hint or "") for i in et17_list
    ), et17_list
    must_raise(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) AS items "
        "RETURN CASE WHEN size(items) > 0 THEN items ELSE ['x'] END LIMIT 20",
        "Case",
        "CASE",
        "list",
    )
    et17_map = soft_issues(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) AS items "
        "RETURN CASE WHEN size(items) > 0 THEN items ELSE {a: 1} END LIMIT 20"
    )
    assert any(
        "Case" in i.message or "CASE" in i.message or "ET-17" in (i.hint or "") for i in et17_map
    ), et17_map
    must_raise(
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) AS items "
        "RETURN CASE WHEN size(items) > 0 THEN items ELSE {a: 1} END LIMIT 20",
        "Case",
        "CASE",
        "map",
        "list",
    )

    # Var-length hop caps / unbounded * — query_guard / prevalid only; cypherast OK
    for q in (
        "MATCH (a:Metric)-[:DERIVED_FROM*]->(b:Metric) RETURN a.name LIMIT 20",
        "MATCH (a:Metric)-[:DERIVED_FROM*0..6]->(b:Metric) RETURN a.name LIMIT 20",
    ):
        opt = cypherast.optimize(q, write="puppygraph")
        issues = cypherast.validate(opt, dialect="puppygraph")
        assert not any(
            "hops" in i.message.lower()
            or "unbounded" in i.message.lower()
            or "variable-length" in i.message.lower()
            for i in issues
        )

    cart = soft_issues("MATCH (a:Metric), (b:Metric) RETURN a.name LIMIT 20")
    assert any("Cartesian" in i.message or "Multiple paths" in i.message for i in cart)
    must_raise(
        "MATCH (a:Metric), (b:Metric) RETURN a.name LIMIT 20",
        "Cartesian",
        "Multiple paths",
    )

    pjt97 = soft_issues(
        "MATCH (a:Metric)-[:R]->(b:Metric) RETURN DISTINCT a.name AS n, count(b) AS c LIMIT 20"
    )
    assert any("DISTINCT" in i.message and "aggregate" in i.message for i in pjt97)
    must_raise(
        "MATCH (a:Metric)-[:R]->(b:Metric) RETURN DISTINCT a.name AS n, count(b) AS c LIMIT 20",
        "DISTINCT",
        "aggregate",
    )

    # FET-45: optimize wraps with CASE null guard
    fet45_q = (
        "MATCH (m:Metric) OPTIONAL MATCH (m)-[:DERIVED_FROM]->(b:Metric) RETURN id(b) LIMIT 20"
    )
    assert any(
        "OPTIONAL-bound" in i.message for i in cypherast.validate(fet45_q, dialect="puppygraph")
    )
    fet45_opt = cypherast.optimize(fet45_q, write="puppygraph")
    out45 = fet45_opt.cypher(dialect="puppygraph")
    assert "CASE WHEN" in out45.upper() and "IS NULL" in out45.upper()
    assert not any(
        "OPTIONAL-bound" in i.message for i in cypherast.validate(fet45_opt, dialect="puppygraph")
    )

    ideq = soft_issues("MATCH (m:Metric) WHERE id(m) = 'bare_key' RETURN m LIMIT 20")
    assert any("string" in i.message.lower() or "toString" in i.message for i in ideq)
    must_raise(
        "MATCH (m:Metric) WHERE id(m) = 'bare_key' RETURN m LIMIT 20",
        "string",
        "toString",
    )


def test_unwind_collect_node_reuse_ok():
    """UNWIND collect(node) AS x then (x) is bound reuse — not CG1402."""
    q = (
        "MATCH (m:Metric) WITH collect(DISTINCT m) AS metrics "
        "UNWIND metrics AS metric "
        "OPTIONAL MATCH (ds:Dataset)-[:INCLUDES_METRIC]->(metric) "
        "RETURN count(DISTINCT ds)"
    )
    opt = cypherast.optimize(q, write="puppygraph")
    issues = cypherast.validate(opt, dialect="puppygraph")
    assert not any(i.code == "CG1402" for i in issues)


def test_bound_reuse_labelled_ok():
    """P0 #1: bare (m) after labelled bind is not unlabelled error."""
    q = (
        "MATCH (m:Metric) MATCH (m)-[:DERIVED_FROM]->(x:Metric) "
        "RETURN count(DISTINCT m.name), count(DISTINCT x.name) LIMIT 20"
    )
    opt = cypherast.optimize(q, write="puppygraph")
    assert not any(i.code == "CG1402" for i in cypherast.validate(opt, dialect="puppygraph"))


def test_not_double_paren_pattern_predicate():
    """P0 #2: WHERE NOT ((path)) and (n)--() must parse."""
    for q in (
        "MATCH (m:Metric) WHERE NOT ((m)-[:DERIVED_FROM]->(:Metric)) RETURN m LIMIT 20",
        "MATCH (n:person) WHERE NOT (n)--(:person) RETURN n LIMIT 20",
        "MATCH (n:person) WHERE ((n)-[:knows]->(:person)) RETURN n LIMIT 20",
    ):
        tree = cypherast.parse_one(q, read="puppygraph")
        assert tree is not None


def test_fet45_optimize_adds_null_guard():
    """FET-45: optimize wraps OPTIONAL id()/split use in CASE WHEN … IS NULL."""
    q = (
        "MATCH (m:Metric) OPTIONAL MATCH (cat:Catalog)-[:HAS_SOURCE]->(st:SourceTable) "
        "RETURN replace(split(toString(id(cat)), '[')[1], ']', '') AS table LIMIT 20"
    )
    assert any("OPTIONAL-bound" in i.message for i in cypherast.validate(q, dialect="puppygraph"))
    opt = cypherast.optimize(q, write="puppygraph")
    out = opt.cypher(dialect="puppygraph")
    assert "CASE WHEN" in out.upper()
    assert "cat IS NULL" in out.replace("  ", " ")
    assert "AS table" in out
    assert not any(
        "OPTIONAL-bound" in i.message for i in cypherast.validate(opt, dialect="puppygraph")
    )


def test_optimize_strips_nulls_order():
    out = cypherast.optimize(
        "MATCH (n:person) RETURN n.name ORDER BY n.name NULLS LAST LIMIT 20",
        write="puppygraph",
    ).cypher(dialect="puppygraph")
    assert "NULLS" not in out.upper()


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
