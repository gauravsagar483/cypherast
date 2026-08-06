"""Canonicalizer + dialect constraint rule catalogs."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.dialects.constraints import (
    bound_variable_length,
    cap_collect_distinct,
    drop_distinct_beside_aggregate,
    ensure_row_limit,
    split_multi_path_match,
)
from cypherast.optimizer.engine import Rule, RuleSet
from cypherast.rewriter.annotate_types import annotate_types
from cypherast.rewriter.canonicalize_patterns import canonicalize_patterns
from cypherast.rewriter.merge_match_chains import merge_match_chains
from cypherast.rewriter.pushdown_predicates import pushdown_predicates
from cypherast.rewriter.qualify import qualify
from cypherast.rewriter.simplify import simplify

# ---------------------------------------------------------------------------
# Shared canonicalizer rules (order matters)
# ---------------------------------------------------------------------------

RULES = RuleSet(
    [
        Rule("qualify", qualify),
        Rule("canonicalize_patterns", canonicalize_patterns),
        Rule("simplify", simplify),
        Rule("pushdown_predicates", pushdown_predicates),
        Rule("annotate_types", annotate_types),
    ]
)

# Opt-in (not in default RULES — Cartesian risk on some engines)
OPTIONAL_RULES = RuleSet(
    [
        Rule("merge_match_chains", merge_match_chains),
    ]
)

ALL_CANONICAL_RULES = RULES + OPTIONAL_RULES


def constraint_rules(caps: DialectCapabilities) -> RuleSet:
    """Build dialect constraint RuleSet from a capabilities snapshot."""
    rules: list[Rule] = []

    if caps.max_var_length_hops is not None or not caps.allow_unbounded_var_length:
        max_hops = caps.max_var_length_hops or 5
        allow_unbounded = caps.allow_unbounded_var_length

        def _bound(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
            _ = schema
            return bound_variable_length(
                tree, max_hops=max_hops, allow_unbounded=allow_unbounded
            )

        rules.append(Rule("bound_variable_length", _bound))

    if not caps.allow_cartesian_match_paths:

        def _split(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
            _ = schema
            return split_multi_path_match(tree)

        rules.append(Rule("split_multi_path_match", _split))

    if caps.require_limit_on_row_return:
        limit = caps.default_row_limit

        def _limit(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
            _ = schema
            return ensure_row_limit(tree, limit=limit)

        rules.append(Rule("ensure_row_limit", _limit))

    if not caps.allow_distinct_with_aggregate:

        def _distinct(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
            _ = schema
            return drop_distinct_beside_aggregate(tree)

        rules.append(Rule("drop_distinct_beside_aggregate", _distinct))

    if caps.max_collect_distinct_per_clause is not None:
        max_n = caps.max_collect_distinct_per_clause

        def _collect(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
            _ = schema
            return cap_collect_distinct(tree, max_n=max_n)

        rules.append(Rule("cap_collect_distinct", _collect))

    return RuleSet(rules)
