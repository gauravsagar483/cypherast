"""openCypher 9 dialect (first read/write dialect over GQL-forward IR)."""

from __future__ import annotations

import typing as t

from cypherast import ast as a
from cypherast.dialects.capabilities import OPENCYPHER9_CAPABILITIES, DialectCapabilities
from cypherast.dialects.dialect import Dialect, register
from cypherast.renderer import Renderer


class OpenCypherRenderer(Renderer):
    dialect_name = "opencypher"
    # Allow quantified path render; strict OC9 validate rejects when opted in.
    unsupported: set[type[a.AstNode]] = Renderer.unsupported - {a.QuantifiedPath}

    def render_PatternPredicate(self, node: a.PatternPredicate) -> str:
        # OC9 pattern expressions — bare (pattern), not exists() function form.
        body = self.dispatch(node.pattern)
        if isinstance(node.pattern, (a.Query, a.Union, a.Cypher)):
            text = f"EXISTS {{ {body} }}"
            return f"NOT {text}" if node.not_ else text
        if isinstance(node.pattern, a.PathPattern):
            return f"NOT ({body})" if node.not_ else f"({body})"
        return f"NOT {body}" if node.not_ else body


@register
class OpenCypher(Dialect):
    """Canonical openCypher 9 surface. Subclass for openCypher-compatible engines."""

    name = "opencypher"
    aliases: t.ClassVar[list[str]] = ["cypher", "oc", "open_cypher"]
    capabilities: t.ClassVar[DialectCapabilities] = OPENCYPHER9_CAPABILITIES
    renderer_cls: t.ClassVar[type[Renderer]] = OpenCypherRenderer

    @classmethod
    def renderer(cls) -> Renderer:
        return cls.renderer_cls()


@register
class OpenCypher9(OpenCypher):
    """Alias for ``OpenCypher`` (openCypher 9 capabilities)."""

    name = "opencypher9"
    aliases: t.ClassVar[list[str]] = ["oc9", "opencypher_9"]
