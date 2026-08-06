"""Dialect package."""

from cypherast.dialects import memgraph as _memgraph  # noqa: F401
from cypherast.dialects import neo4j as _neo4j  # noqa: F401
from cypherast.dialects import opencypher as _opencypher  # noqa: F401
from cypherast.dialects import puppygraph as _puppygraph  # noqa: F401
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.dialects.dialect import (
    Dialect,
    dialect_names,
    get_dialect,
    get_dialect_cls,
    register,
)

__all__ = [
    "Dialect",
    "DialectCapabilities",
    "dialect_names",
    "get_dialect",
    "get_dialect_cls",
    "register",
]
