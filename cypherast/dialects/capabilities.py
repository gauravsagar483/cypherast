"""Per-dialect engine capability flags (generic — no graph-domain labels)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DialectCapabilities:
    """What a target engine accepts. Dialects override; rewriters/validators consult."""

    # Patterns
    require_labelled_nodes: bool = False
    allow_cartesian_match_paths: bool = True
    max_var_length_hops: int | None = None  # None = unbounded OK
    allow_unbounded_var_length: bool = True

    # Predicates / expressions
    allow_exists_function: bool = True
    allow_list_comprehension: bool = True
    allow_pattern_comprehension: bool = True
    allow_list_concat: bool = True
    allow_node_in_list_membership: bool = True

    # Aggregation / projection
    max_collect_distinct_per_clause: int | None = None  # None = unlimited
    allow_distinct_with_aggregate: bool = True
    allow_nulls_order_modifiers: bool = True

    # Result shaping
    require_limit_on_row_return: bool = False
    default_row_limit: int = 20

    # Pattern predicates in WHERE
    pattern_predicate_introduces_bindings: bool = True  # openCypher may; some engines forbid
