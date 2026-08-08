"""Memgraph dialect (Neo4j Cypher 5 base + Memgraph-specific surface)."""

from __future__ import annotations

import typing as t

from cypherast.dialects.capabilities import MEMGRAPH_CAPABILITIES
from cypherast.dialects.cypher import CypherRenderer, build_unsupported
from cypherast.dialects.dialect import register
from cypherast.dialects.neo4j import Neo4jCypher5
from cypherast.renderer import Renderer


class MemgraphRenderer(CypherRenderer):
    dialect_name = "memgraph"
    capabilities = MEMGRAPH_CAPABILITIES
    unsupported = build_unsupported(MEMGRAPH_CAPABILITIES)


@register
class Memgraph(Neo4jCypher5):
    name = "memgraph"
    aliases = ["mg"]
    capabilities = MEMGRAPH_CAPABILITIES
    renderer_cls: t.ClassVar[type[Renderer]] = MemgraphRenderer
