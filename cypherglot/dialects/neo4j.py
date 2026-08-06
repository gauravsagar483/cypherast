"""Neo4j Cypher 5 dialect."""

from __future__ import annotations

from cypherglot import ast as a
from cypherglot.dialects.dialect import Dialect, register
from cypherglot.renderer import Renderer


class Neo4jRenderer(Renderer):
    dialect_name = "neo4j"
    # Neo4j can express more; still reject pure GQL session/graph-type DDL for now
    unsupported: set[type[a.AstNode]] = {
        a.CreateGraphType,
        a.GraphTypeRef,
        a.SessionCommand,
        a.TransactionCommand,
        a.BindingTable,
        a.ValueTable,
    }


@register
class Neo4j(Dialect):
    name = "neo4j"
    aliases = ["neo", "cypher5"]

    @classmethod
    def renderer(cls) -> Renderer:
        return Neo4jRenderer()
