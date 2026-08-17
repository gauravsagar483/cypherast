"""Per-dialect engine capability flags (generic — no graph-domain labels)."""

from __future__ import annotations

from dataclasses import dataclass, replace


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
    allow_map_projection: bool = True
    allow_exists_subquery: bool = True
    allow_count_subquery: bool = True
    allow_list_concat: bool = True
    allow_node_in_list_membership: bool = True
    allow_parameters: bool = True
    # id()/elementId() used with CONTAINS / STARTS WITH / ENDS WITH / = string
    allow_id_in_string_predicates: bool = True
    allow_element_id_in_string_predicates: bool = True
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
    # Function policy overlays. Names are lowercase. Arity triples are
    # ``(name, min_args, max_args)`` and override the shared catalog.
    allowed_functions: frozenset[str] = frozenset()
    unsupported_functions: frozenset[str] = frozenset()
    function_arity_overrides: tuple[tuple[str, int, int], ...] = ()

    # Aggregation / projection
    max_collect_distinct_per_clause: int | None = None  # None = unlimited
    # When False, do not rewrite extra collect(DISTINCT) → count(DISTINCT)
    rewrite_collect_distinct_cap: bool = True
    # TE-14: collect(DISTINCT) alone in a clause (no sibling aggregates)
    allow_collect_distinct_with_other_aggregates: bool = True
    allow_distinct_with_aggregate: bool = True
    # When False, do not silently drop DISTINCT beside aggregates (reject via validate)
    rewrite_distinct_beside_aggregate: bool = True
    # When False, a projection item may not combine an aggregate with a bare
    # reference (``RETURN n.age + count(*)``); grouping keys must be standalone.
    # PuppyGraph's AggregationMixingCheck is stricter than Neo4j here (Neo4j
    # accepts an exact standalone grouping key inside the aggregate expression),
    # so only PuppyGraph sets this off.
    allow_mixed_aggregate_projection: bool = True
    allow_nulls_order_modifiers: bool = True
    allow_multi_label_nodes: bool = True

    # Result shaping
    require_matching_union_columns: bool = False
    check_undefined_variables: bool = False
    allow_write_clauses: bool = True

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

    # Cypher 25 / Neo4j 25 feature gates (parse + validate)
    allow_filter_clause: bool = False
    allow_for_clause: bool = False
    allow_let_clause: bool = False
    allow_search_clause: bool = False
    allow_when_query: bool = False
    allow_group_by_subclause: bool = False
    allow_call_variable_import: bool = False
    allow_call_in_transactions: bool = False
    allow_optional_call: bool = False
    allow_inline_pattern_where: bool = False
    allow_label_expressions: bool = False
    allow_dynamic_labels: bool = False
    allow_load_csv: bool = False
    allow_admin_ddl: bool = False
    # Memgraph-specific relationship quantifiers (*bfs..N, *wShortest)
    allow_memgraph_rel_quantifiers: bool = False


DEFAULT_CYPHER_CAPABILITIES = DialectCapabilities()

NEO4J5_CAPABILITIES = DialectCapabilities(
    reject_gql_nodes=True,
    allow_call_variable_import=True,
    allow_inline_pattern_where=True,
    allow_label_expressions=True,
    allow_load_csv=True,
)

NEO4J25_CAPABILITIES = replace(
    NEO4J5_CAPABILITIES,
    allow_filter_clause=True,
    allow_for_clause=True,
    allow_let_clause=True,
    allow_search_clause=True,
    allow_when_query=True,
    allow_group_by_subclause=True,
    allow_call_in_transactions=True,
    allow_optional_call=True,
    allow_dynamic_labels=True,
)

MEMGRAPH_CAPABILITIES = replace(
    NEO4J5_CAPABILITIES,
    reject_quantified_path=True,
    allow_admin_ddl=True,
    allow_memgraph_rel_quantifiers=True,
)

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
