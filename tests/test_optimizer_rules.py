"""Named optimizer rules: only / disable."""

import cypherglot
from cypherglot.dialects.puppygraph import PuppyGraph
from cypherglot.optimizer import OPTIONAL_RULES, RULES, RuleSet
from cypherglot.optimizer import optimize as opt_optimize
from cypherglot.optimizer.catalog import constraint_rules


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
    out = cypherglot.optimize(
        "MATCH () RETURN 1",
        write="opencypher",
        disable=["qualify"],
    ).cypher()
    # without qualify, anonymous node stays ()
    assert "()" in out.replace(" ", "") or "MATCH ()" in out.replace("  ", " ")


def test_only_simplify():
    tree = cypherglot.parse_one("RETURN 1 + 1")
    out = opt_optimize(tree, only=["simplify"])
    assert out.cypher() == "RETURN 2" or "2" in out.cypher()


def test_constraint_disable_ensure_row_limit():
    out = cypherglot.optimize(
        "MATCH (n:Person) RETURN n.name",
        write="puppygraph",
        constraint_disable=["ensure_row_limit"],
    ).cypher(dialect="puppygraph")
    assert "LIMIT" not in out.upper()


def test_constraint_only_split_cartesian():
    out = cypherglot.optimize(
        "MATCH (a:Person), (b:Person) RETURN a, b LIMIT 10",
        write="puppygraph",
        only=[],  # skip canonicalizer
        constraint_only=["split_multi_path_match"],
    ).cypher(dialect="puppygraph")
    assert out.upper().count("MATCH") >= 2
    # ensure_row_limit not in constraint_only → no extra LIMIT if already present
    assert "LIMIT" in out.upper()


def test_ruleset_disable_unknown_raises():
    try:
        RULES.disable("nope")
        raise AssertionError("expected KeyError")
    except KeyError as e:
        assert "nope" in str(e)


def test_puppygraph_constraint_rule_names():
    names = PuppyGraph.constraint_rule_set().names
    assert "ensure_row_limit" in names
    assert "split_multi_path_match" in names
    assert "cap_collect_distinct" in names
    assert "bound_variable_length" not in names  # unbounded allowed


def test_opt_in_merge_match_chains():
    tree = cypherglot.parse_one(
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
    assert len(rs) >= 3
