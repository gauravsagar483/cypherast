"""Per-dialect engine capability flags (generic — no graph-domain labels)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DialectCapabilities:
    """What a target engine accepts. Dialects override; rewriters/validators consult.

    Non-goals (callers / external tools):
    - Declared-schema property existence / ID-vs-property field rules
      (e.g. ``dq.dq_check_id`` vs ``id(dq)``) — needs caller ``GraphSchema``;
      validate does not invent domain property catalogs.
    - Query-guard hop caps (e.g. MAX_HOPS=5) — engine/prevalid concern;
      PuppyGraph leaves unbounded / high ``*lo..hi`` alone unless a dialect
      sets ``max_var_length_hops`` / ``allow_unbounded_var_length=False``.
    """

    # Patterns
    require_labelled_nodes: bool = False
    allow_cartesian_match_paths: bool = True
    # When False, validate rejects comma multi-path; do not split into consecutive MATCH
    rewrite_cartesian_match_paths: bool = True
    max_var_length_hops: int | None = None  # None = unbounded OK
    allow_unbounded_var_length: bool = True
    # When False, only validate hop bounds — do not rewrite * / *N into capped form
    rewrite_var_length_bounds: bool = True

    # Predicates / expressions
    allow_exists_function: bool = True
    allow_list_comprehension: bool = True
    allow_pattern_comprehension: bool = True
    allow_list_concat: bool = True
    allow_node_in_list_membership: bool = True
    # id()/elementId() used with CONTAINS / STARTS WITH / ENDS WITH / = string
    allow_id_in_string_predicates: bool = True
    # OPTIONAL-bound vars in id()/split/… without null guard (FET-45).
    # When False, validate rejects; set rewrite_unguarded_optional_scalar_use
    # to wrap with CASE WHEN var IS NULL THEN NULL ELSE … END.
    allow_unguarded_optional_scalar_use: bool = True
    rewrite_unguarded_optional_scalar_use: bool = False
    # Function names (lowercased) treated as FET-45 risky when applied to
    # OPTIONAL-bound vars. Empty = no-op for guard/validate of this class.
    optional_risky_functions: frozenset[str] = frozenset()
    # PuppyGraph ET-16/ET-17: CASE THEN/ELSE arms must share a compatible shape.
    # When False, reject list↔list-literal, list↔map, list↔scalar, map↔scalar.
    allow_mismatched_case_arms: bool = True

    # Aggregation / projection
    max_collect_distinct_per_clause: int | None = None  # None = unlimited
    # When False, do not rewrite extra collect(DISTINCT) → count(DISTINCT)
    rewrite_collect_distinct_cap: bool = True
    # TE-14: collect(DISTINCT) alone in a clause (no sibling aggregates)
    allow_collect_distinct_with_other_aggregates: bool = True
    allow_distinct_with_aggregate: bool = True
    # When False, do not silently drop DISTINCT beside aggregates (reject via validate)
    rewrite_distinct_beside_aggregate: bool = True
    allow_nulls_order_modifiers: bool = True

    # Result shaping
    require_matching_union_columns: bool = False
    check_undefined_variables: bool = False

    # Pattern predicates in WHERE
    pattern_predicate_introduces_bindings: bool = True  # openCypher may; some engines forbid

    # openCypher 9 validation (enabled on ``OPENCYPHER9_CAPABILITIES`` / ``OpenCypher``)
    check_function_signatures: bool = False
    reject_excluded_clauses: bool = False
    reject_undirected_patterns: bool = False
    reject_var_length_binding: bool = False
    reject_call_subquery: bool = False
    reject_gql_nodes: bool = False
    reject_quantified_path: bool = False
    reject_using_hints: bool = False
    check_comparability: bool = False


OPENCYPHER9_CAPABILITIES = DialectCapabilities(
    check_undefined_variables=True,
    allow_exists_function=False,
    pattern_predicate_introduces_bindings=True,
    check_function_signatures=True,
    reject_excluded_clauses=True,
    reject_undirected_patterns=True,
    reject_var_length_binding=True,
    reject_call_subquery=True,
    reject_gql_nodes=True,
    reject_quantified_path=True,
    reject_using_hints=True,
    check_comparability=True,
)
