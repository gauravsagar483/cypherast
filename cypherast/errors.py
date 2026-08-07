"""Exception hierarchy and stable error-code registry for cypherast."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Position:
    """Source location (1-indexed line/col, 0-indexed offset)."""

    line: int = 1
    col: int = 1
    offset: int = 0

    def __str__(self) -> str:
        return f"line {self.line}:{self.col}"


# Stable error codes — tools branch on these, not message strings.
ERROR_CODES: dict[str, str] = {
    # Tokenizer CG10xx
    "CG1001": "Illegal character",
    "CG1002": "Unterminated string literal",
    "CG1003": "Unterminated comment",
    "CG1004": "Invalid number literal",
    "CG1005": "Invalid parameter name",
    # Parser CG11xx
    "CG1101": "Unexpected token",
    "CG1102": "Mismatched input",
    "CG1103": "Unexpected end of input",
    "CG1104": "Invalid pattern",
    # Validation CG12xx
    "CG1201": "Unknown variable",
    "CG1202": "Scope violation",
    "CG1203": "Invalid RETURN / projection",
    "CG1204": "Duplicate binding",
    # Schema CG13xx
    "CG1301": "Unknown label",
    "CG1302": "Unknown relationship type",
    "CG1303": "Unknown property",
    "CG1304": "Endpoint constraint violation",
    "CG1305": "Id field used as property",
    # Compatibility CG14xx
    "CG1401": "Construct not supported by target dialect",
    "CG1402": "Unlabelled node pattern not allowed by target dialect",
    # Optimize CG15xx
    "CG1501": "Rewrite failed",
    # Plan CG16xx
    "CG1601": "No viable plan",
    "CG1602": "Plan enumeration exceeded max plans",
    # Execute CG17xx
    "CG1701": "Runtime type error",
    "CG1702": "Evaluation error",
    "CG1703": "Write conflict",
    "CG1704": "Missing graph / table",
}


class CypherastError(Exception):
    """Base error. Every raise carries a stable ``code``."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        position: Position | None = None,
        hint: str | None = None,
        source: str | None = None,
        expected: set[str] | None = None,
        **extra: Any,
    ) -> None:
        self.code = code
        self.position = position
        self.hint = hint
        self.source = source
        self.expected = expected
        self.extra = extra
        super().__init__(self._format(message))

    def _format(self, message: str) -> str:
        parts: list[str] = [f"[{self.code}]"]
        if self.position is not None:
            parts.append(str(self.position))
        parts.append(message)
        text = " ".join(parts)
        if self.expected:
            exp = ", ".join(sorted(self.expected))
            text += f"; expected {{{exp}}}"
        if self.source and self.position is not None:
            text += "\n" + self._caret(self.source, self.position)
        if self.hint:
            text += f"\nHint: {self.hint}"
        return text

    @staticmethod
    def _caret(source: str, pos: Position) -> str:
        lines = source.splitlines() or [""]
        idx = max(0, min(pos.line - 1, len(lines) - 1))
        line = lines[idx]
        caret = " " * max(0, pos.col - 1) + "^"
        return f"  {line}\n  {caret}"


class TokenizeError(CypherastError):
    """Lexical analysis failure (CG10xx)."""


class ParseError(CypherastError):
    """Syntactic analysis failure (CG11xx)."""


class ValidationError(CypherastError):
    """Semantic validation failure (CG12xx)."""


class SchemaError(CypherastError):
    """Schema / catalog failure (CG13xx)."""


class CompatibilityError(CypherastError):
    """Source construct not expressible in target dialect (CG14xx)."""


class OptimizeError(CypherastError):
    """Rewriter failure (CG15xx)."""


class PlanError(CypherastError):
    """Planner failure (CG16xx)."""


class ExecuteError(CypherastError):
    """Runtime execution failure (CG17xx)."""


class ErrorCollector:
    """Accumulate diagnostics instead of fail-fast (``errors='collect'``)."""

    def __init__(self) -> None:
        self.errors: list[CypherastError] = []

    def add(self, err: CypherastError) -> None:
        self.errors.append(err)

    def raise_if_any(self) -> None:
        if not self.errors:
            return
        if len(self.errors) == 1:
            raise self.errors[0]
        msgs = "\n".join(str(e) for e in self.errors)
        raise CypherastError(
            f"{len(self.errors)} errors:\n{msgs}",
            code="CG1102",
        )

    def __bool__(self) -> bool:
        return bool(self.errors)
