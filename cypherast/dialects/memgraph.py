"""Memgraph dialect."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.dialect import Dialect, register
from cypherast.renderer import Renderer


class MemgraphRenderer(Renderer):
    dialect_name = "memgraph"
    unsupported: set[type[a.AstNode]] = {
        a.Next,
        a.Insert,
        a.CreateGraphType,
        a.GraphTypeRef,
        a.SessionCommand,
        a.TransactionCommand,
        a.BindingTable,
        a.ValueTable,
        a.Use,
        a.QuantifiedPath,
    }


@register
class Memgraph(Dialect):
    name = "memgraph"
    aliases = ["mg"]

    @classmethod
    def renderer(cls) -> Renderer:
        return MemgraphRenderer()
