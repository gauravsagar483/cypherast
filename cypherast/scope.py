"""Binding scopes across WITH / UNWIND / UNION / subqueries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from cypherast import ast as a


class ScopeType(Enum):
    ROOT = auto()
    WITH = auto()
    UNWIND = auto()
    UNION = auto()
    SUBQUERY = auto()


@dataclass
class Scope:
    expression: a.AstNode
    scope_type: ScopeType = ScopeType.ROOT
    parent: Scope | None = None
    bindings: dict[str, a.AstNode] = field(default_factory=dict)
    children: list[Scope] = field(default_factory=list)

    def define(self, name: str, node: a.AstNode) -> None:
        self.bindings[name] = node

    def resolve(self, name: str) -> a.AstNode | None:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.resolve(name)
        return None


def _binding_name(expr: a.AstNode) -> str | None:
    if isinstance(expr, a.Alias):
        if isinstance(expr.alias, a.Identifier):
            return str(expr.alias.this)
        return None
    if isinstance(expr, a.Identifier):
        return str(expr.this)
    if isinstance(expr, a.Property) and isinstance(expr.this, a.Identifier):
        return str(expr.name)
    return None


def build_scope(tree: a.AstNode) -> Scope:
    """Build binding scopes from a Cypher AST."""
    root_expr = tree.this if isinstance(tree, a.Cypher) else tree
    root = Scope(expression=root_expr, scope_type=ScopeType.ROOT)
    _walk_query(root_expr, root)
    return root


def _walk_query(node: a.AstNode, scope: Scope) -> Scope:
    if isinstance(node, a.Union):
        left = Scope(expression=node.this, scope_type=ScopeType.UNION, parent=scope)
        right = Scope(expression=node.expression, scope_type=ScopeType.UNION, parent=scope)
        scope.children.extend([left, right])
        _walk_query(node.this, left)
        _walk_query(node.expression, right)
        return scope
    if isinstance(node, a.Query):
        current = scope
        for clause in node.clauses:
            current = _walk_clause(clause, current)
        return current
    return scope


def _walk_clause(clause: a.AstNode, scope: Scope) -> Scope:
    if isinstance(clause, a.Match):
        _collect_pattern_vars(clause.pattern, scope)
        return scope
    if isinstance(clause, a.Unwind):
        child = Scope(expression=clause, scope_type=ScopeType.UNWIND, parent=scope)
        scope.children.append(child)
        if isinstance(clause.alias, a.Identifier):
            child.define(clause.alias.this, clause.alias)
        return child
    if isinstance(clause, a.With):
        child = Scope(expression=clause, scope_type=ScopeType.WITH, parent=scope)
        scope.children.append(child)
        for expr in clause.expressions or []:
            name = _binding_name(expr)
            if name:
                child.define(name, expr)
        return child
    if isinstance(clause, a.Return):
        for expr in clause.expressions or []:
            name = _binding_name(expr)
            if name:
                scope.define(name, expr)
        return scope
    if isinstance(clause, a.CallProcedure):
        if clause.yield_ is not None:
            for expr in clause.yield_.expressions or []:
                if isinstance(expr, a.Star):
                    continue
                name = _binding_name(expr)
                if name:
                    scope.define(name, expr)
        return scope
    if isinstance(clause, (a.Create, a.Merge, a.Insert)):
        _collect_pattern_vars(clause.pattern, scope)
        return scope
    return scope


def _collect_pattern_vars(pattern: a.AstNode | None, scope: Scope) -> None:
    if pattern is None:
        return
    for node in pattern.walk():
        if isinstance(node, a.NodePattern) and isinstance(node.variable, a.Identifier):
            scope.define(node.variable.this, node.variable)
        if isinstance(node, a.RelationshipPattern) and isinstance(node.variable, a.Identifier):
            scope.define(node.variable.this, node.variable)
        if isinstance(node, a.PathPattern) and isinstance(node.variable, a.Identifier):
            scope.define(node.variable.this, node.variable)
