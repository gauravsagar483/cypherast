"""openCypher 9 dialect (first read/write dialect over GQL-forward IR)."""

from __future__ import annotations

import typing as t

from cypherast.dialects.capabilities import OPENCYPHER9_CAPABILITIES, DialectCapabilities
from cypherast.dialects.cypher import CypherDialect, CypherRenderer, build_unsupported
from cypherast.dialects.dialect import register
from cypherast.renderer import Renderer


class OpenCypherRenderer(CypherRenderer):
    dialect_name = "opencypher"
    pattern_predicate_style: t.ClassVar[t.Literal["exists", "bare"]] = "bare"
    capabilities = OPENCYPHER9_CAPABILITIES
    unsupported = build_unsupported(OPENCYPHER9_CAPABILITIES, quantified_path=True)


@register
class OpenCypher(CypherDialect):
    """Canonical openCypher 9 surface. Subclass for openCypher-compatible engines."""

    name = "opencypher"
    aliases: t.ClassVar[list[str]] = ["cypher", "oc", "open_cypher"]
    capabilities: t.ClassVar[DialectCapabilities] = OPENCYPHER9_CAPABILITIES
    renderer_cls: t.ClassVar[type[Renderer]] = OpenCypherRenderer


@register
class OpenCypher9(OpenCypher):
    """Alias for ``OpenCypher`` (openCypher 9 capabilities)."""

    name = "opencypher9"
    aliases: t.ClassVar[list[str]] = ["oc9", "opencypher_9"]
