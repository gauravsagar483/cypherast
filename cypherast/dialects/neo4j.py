"""Neo4j Cypher dialects (pinned Cypher 5 and latest Cypher 25)."""

from __future__ import annotations

import typing as t

from cypherast.dialects.capabilities import NEO4J5_CAPABILITIES, NEO4J25_CAPABILITIES
from cypherast.dialects.cypher import CypherDialect, CypherRenderer, build_unsupported
from cypherast.dialects.dialect import register
from cypherast.renderer import Renderer


class Neo4jCypher5Renderer(CypherRenderer):
    dialect_name = "neo4j5"
    capabilities = NEO4J5_CAPABILITIES
    unsupported = build_unsupported(
        NEO4J5_CAPABILITIES,
        quantified_path=True,
        use_clause=True,
        insert_clause=True,
        next_clause=True,
    )


class Neo4jCypher25Renderer(Neo4jCypher5Renderer):
    dialect_name = "neo4j25"
    capabilities = NEO4J25_CAPABILITIES
    unsupported = build_unsupported(
        NEO4J25_CAPABILITIES,
        quantified_path=True,
        use_clause=True,
        insert_clause=True,
        next_clause=True,
    )


@register
class Neo4jCypher5(CypherDialect):
    name = "neo4j5"
    aliases = ["cypher5"]
    capabilities = NEO4J5_CAPABILITIES
    renderer_cls: t.ClassVar[type[Renderer]] = Neo4jCypher5Renderer


@register
class Neo4jCypher25(Neo4jCypher5):
    name = "neo4j25"
    aliases = ["neo4j", "neo"]
    capabilities = NEO4J25_CAPABILITIES
    renderer_cls: t.ClassVar[type[Renderer]] = Neo4jCypher25Renderer
