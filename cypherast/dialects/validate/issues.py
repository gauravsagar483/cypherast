"""ConstraintIssue dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConstraintIssue:
    code: str
    message: str
    hint: str | None = None
