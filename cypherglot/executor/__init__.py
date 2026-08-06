"""Executor package."""

from cypherglot.executor.engine import Result, execute
from cypherglot.executor.graph import Graph, Node, Relationship

__all__ = ["Graph", "Node", "Relationship", "Result", "execute"]
