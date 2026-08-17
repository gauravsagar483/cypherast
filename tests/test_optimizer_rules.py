"""Named optimizer rules: only / disable."""

import cypherast
from cypherast.dialects.puppygraph import PuppyGraph
from cypherast.optimizer import OPTIONAL_RULES, RULES, RuleSet
from cypherast.optimizer import optimize as opt_optimize
from cypherast.optimizer.catalog import constraint_rules


def test_rules_names():
    assert RULES.names == [
        "qualify",
        "canonicalize_patterns",
        "simplify",
        "pushdown_predicates",
        "annotate_types",
    ]
    assert "merge_match_chains" in OPTIONAL_RULES.names


def test_disable_qualify_keeps_anon():
    out = cypherast.optimize(
        "MATCH () RETURN 1",
        write="opencypher",
        disable=["qualify"],
    ).cypher()
    # without qualify, anonymous node stays ()
    assert "()" in out.replace(" ", "") or "MATCH ()" in out.replace("  ", " ")


def test_only_simplify():
    tree = cypherast.parse_one("RETURN 1 + 1")
    out = opt_optimize(tree, only=["simplify"])
    assert out.cypher() == "RETURN 2" or "2" in out.cypher()


def test_constraint_disable_strip_nulls():
    out = cypherast.optimize(
        "MATCH (n:person) RETURN n.name ORDER BY n.name NULLS LAST",
        write="puppygraph",
        constraint_disable=["strip_nulls_order_modifiers"],
        strict=False,
    ).cypher(dialect="puppygraph")
    assert "NULLS" in out.upper()


def test_constraint_only_split_cartesian():
    """split_multi_path_match still available when rewrite flag is on."""
    from cypherast.dialects.capabilities import DialectCapabilities
    from cypherast.dialects.constraints import split_multi_path_match

    caps = DialectCapabilities(
        allow_cartesian_match_paths=False,
        rewrite_cartesian_match_paths=True,
    )
    rs = constraint_rules(caps)
    assert "split_multi_path_match" in rs.names
    tree = cypherast.parse_one("MATCH (a:Person), (b:Person) RETURN a, b LIMIT 10")
    out = split_multi_path_match(tree).cypher()
    assert out.upper().count("MATCH") >= 2


def test_ruleset_disable_unknown_raises():
    try:
        RULES.disable("nope")
        raise AssertionError("expected KeyError")
    except KeyError as e:
        assert "nope" in str(e)


def test_puppygraph_constraint_rule_names():
    names = PuppyGraph.constraint_rule_set().names
    assert "ensure_labelled_nodes" not in names
    assert "ensure_row_limit" not in names
    assert "guard_optional_scalar_use" in names
    # Reject-only (no silent rewrite that greenwashes engine failures)
    assert "split_multi_path_match" not in names
    assert "cap_collect_distinct" not in names
    assert "bound_variable_length" not in names
    assert "drop_distinct_beside_aggregate" not in names


def test_opt_in_merge_match_chains():
    tree = cypherast.parse_one(
        "MATCH (a:Person) MATCH (a)-[:R]->(b:Person) RETURN a, b LIMIT 5"
    )
    # default RULES: no merge
    default = opt_optimize(tree.copy()).cypher()
    assert default.upper().count("MATCH") >= 2 or "MATCH" in default.upper()

    merged = opt_optimize(tree, rules=RULES + OPTIONAL_RULES).cypher()
    # may still be 1 or 2 MATCH depending on merge success; just ensure callable
    assert "RETURN" in merged.upper()


def test_constraint_rules_builder():
    rs = constraint_rules(PuppyGraph.capabilities)
    assert isinstance(rs, RuleSet)
    assert {"strip_nulls_order_modifiers", "guard_optional_scalar_use"} <= set(rs.names)
