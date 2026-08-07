"""Capability rewrite transforms (engine-agnostic)."""

from __future__ import annotations

from cypherast.dialects.transforms.apply import apply_capabilities
from cypherast.dialects.transforms.distinct_aggregate import (
    cap_collect_distinct,
    drop_distinct_beside_aggregate,
)
from cypherast.dialects.transforms.guard_optional_scalar import guard_optional_scalar_use
from cypherast.dialects.transforms.labelled_nodes import ensure_labelled_nodes
from cypherast.dialects.transforms.nulls_order import strip_nulls_order_modifiers
from cypherast.dialects.transforms.split_match import split_multi_path_match
from cypherast.dialects.transforms.var_length import bound_variable_length

__all__ = [
    "apply_capabilities",
    "bound_variable_length",
    "cap_collect_distinct",
    "drop_distinct_beside_aggregate",
    "ensure_labelled_nodes",
    "guard_optional_scalar_use",
    "split_multi_path_match",
    "strip_nulls_order_modifiers",
]
