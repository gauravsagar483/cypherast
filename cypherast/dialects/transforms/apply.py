"""Apply capability rewrites in catalog order."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.dialects.transforms.distinct_aggregate import (
    cap_collect_distinct,
    drop_distinct_beside_aggregate,
)
from cypherast.dialects.transforms.guard_optional_scalar import guard_optional_scalar_use
from cypherast.dialects.transforms.labelled_nodes import ensure_labelled_nodes
from cypherast.dialects.transforms.nulls_order import strip_nulls_order_modifiers
from cypherast.dialects.transforms.split_match import split_multi_path_match
from cypherast.dialects.transforms.var_length import bound_variable_length


def apply_capabilities(
    tree: a.AstNode,
    caps: DialectCapabilities,
    *,
    schema: object | None = None,
) -> a.AstNode:
    """Rewrite tree to satisfy capability constraints where auto-fix is safe."""
    node = tree
    if caps.require_labelled_nodes:
        node = ensure_labelled_nodes(node, schema=schema)
    if caps.rewrite_var_length_bounds and (
        caps.max_var_length_hops is not None or not caps.allow_unbounded_var_length
    ):
        node = bound_variable_length(
            node,
            max_hops=caps.max_var_length_hops or 5,
            allow_unbounded=caps.allow_unbounded_var_length,
        )
    if not caps.allow_cartesian_match_paths and caps.rewrite_cartesian_match_paths:
        node = split_multi_path_match(node)
    if (
        not caps.allow_distinct_with_aggregate
        and caps.rewrite_distinct_beside_aggregate
    ):
        node = drop_distinct_beside_aggregate(node)
    if (
        caps.rewrite_collect_distinct_cap
        and caps.max_collect_distinct_per_clause is not None
    ):
        node = cap_collect_distinct(node, max_n=caps.max_collect_distinct_per_clause)
    if not caps.allow_nulls_order_modifiers:
        node = strip_nulls_order_modifiers(node)
    if caps.rewrite_unguarded_optional_scalar_use:
        node = guard_optional_scalar_use(
            node, risky_functions=caps.optional_risky_functions
        )
    return node
