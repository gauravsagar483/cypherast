"""Generic dialect constraint rewrites + validators (engine-agnostic helpers).

Thin facade — implementations live under ``cypherast.dialects.transforms`` and
``cypherast.dialects.validate``. Callers pass a ``DialectCapabilities`` snapshot.
Label names come from ``GraphSchema`` only — never hard-coded domain vocabulary.
"""

from __future__ import annotations

from cypherast.dialects.transforms import (
    apply_capabilities,
    bound_variable_length,
    cap_collect_distinct,
    drop_distinct_beside_aggregate,
    ensure_labelled_nodes,
    guard_optional_scalar_use,
    split_multi_path_match,
    strip_nulls_order_modifiers,
)
from cypherast.dialects.validate import (
    ConstraintIssue,
    raise_if_invalid,
    validate_capabilities,
)

__all__ = [
    "ConstraintIssue",
    "apply_capabilities",
    "bound_variable_length",
    "cap_collect_distinct",
    "drop_distinct_beside_aggregate",
    "ensure_labelled_nodes",
    "guard_optional_scalar_use",
    "raise_if_invalid",
    "split_multi_path_match",
    "strip_nulls_order_modifiers",
    "validate_capabilities",
]
