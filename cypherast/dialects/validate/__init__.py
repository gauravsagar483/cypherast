"""Capability validators (reject-only)."""

from __future__ import annotations

from cypherast.dialects.validate.dispatch import (
    raise_if_invalid,
    validate_capabilities,
)
from cypherast.dialects.validate.issues import ConstraintIssue

__all__ = [
    "ConstraintIssue",
    "raise_if_invalid",
    "validate_capabilities",
]
