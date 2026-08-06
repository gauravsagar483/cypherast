"""openCypher 9 dialect (first read/write dialect over GQL-forward IR)."""

from __future__ import annotations

import typing as t

from cypherast.dialects.dialect import Dialect, register
from cypherast.renderer import Renderer


class OpenCypherRenderer(Renderer):
    dialect_name = "opencypher"


@register
class OpenCypher(Dialect):
    """Canonical openCypher surface. Subclass for openCypher-compatible engines."""

    name = "opencypher"
    aliases: t.ClassVar[list[str]] = ["cypher", "oc", "open_cypher"]
    renderer_cls: t.ClassVar[type[Renderer]] = OpenCypherRenderer

    @classmethod
    def renderer(cls) -> Renderer:
        return cls.renderer_cls()
