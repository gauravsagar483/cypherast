"""Dialect registry and base Dialect class."""

from __future__ import annotations

import typing as t

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.dialects.constraints import (
    ConstraintIssue,
    raise_if_invalid,
    validate_capabilities,
)
from cypherast.lexer import Lexer
from cypherast.optimizer.engine import RuleSet
from cypherast.parser import Parser
from cypherast.renderer import Renderer


class Dialect:
    """Base dialect. Subclasses override lexer/parser/renderer/capability deltas."""

    name: str = "opencypher"
    aliases: t.ClassVar[list[str]] = []
    capabilities: t.ClassVar[DialectCapabilities] = DialectCapabilities()
    renderer_cls: t.ClassVar[type[Renderer] | None] = None

    @classmethod
    def lexer(cls, source: str) -> Lexer:
        return Lexer(source)

    @classmethod
    def parser(cls, source: str) -> Parser:
        return Parser(source, dialect=cls.name)

    @classmethod
    def renderer(cls) -> Renderer:
        if cls.renderer_cls is not None:
            return cls.renderer_cls()
        r = Renderer()
        r.dialect_name = cls.name
        return r

    @classmethod
    def rewrite_rules(cls) -> RuleSet:
        """Extra canonicalizer rules after shared ``RULES`` (override in subclasses)."""
        return RuleSet()

    @classmethod
    def constraint_rule_set(cls) -> RuleSet:
        """Dialect constraint rules derived from ``capabilities``."""
        from cypherast.optimizer import constraint_rules

        return constraint_rules(cls.capabilities)

    @classmethod
    def apply_constraints(
        cls,
        tree: a.AstNode,
        schema: object | None = None,
        *,
        only: t.Iterable[str] | None = None,
        disable: t.Iterable[str] | None = None,
    ) -> a.AstNode:
        """Rewrite IR via named constraint rules (filterable)."""
        from cypherast.optimizer import resolve_rules

        rules = resolve_rules(cls.constraint_rule_set(), only=only, disable=disable)
        if not len(rules):
            return tree
        return rules.apply(tree, copy=False, schema=schema)

    @classmethod
    def validate(cls, tree: a.AstNode) -> list[ConstraintIssue]:
        """List remaining capability violations (empty = OK)."""
        return validate_capabilities(tree, cls.capabilities)

    @classmethod
    def optimize(
        cls,
        tree: a.AstNode,
        schema: object | None = None,
        *,
        strict: bool = False,
        only: t.Iterable[str] | None = None,
        disable: t.Iterable[str] | None = None,
        constraint_only: t.Iterable[str] | None = None,
        constraint_disable: t.Iterable[str] | None = None,
        rules: RuleSet | None = None,
    ) -> a.AstNode:
        """Canonicalizer + dialect constraints; rules toggleable by name."""
        from cypherast.optimizer import RULES
        from cypherast.optimizer import optimize as opt_optimize

        base = rules if rules is not None else (RULES + cls.rewrite_rules())
        node = opt_optimize(
            tree,
            schema=schema,
            rules=base,
            only=only,
            disable=disable,
            constraints=cls.constraint_rule_set(),
            constraint_only=constraint_only,
            constraint_disable=constraint_disable,
        )
        if strict:
            raise_if_invalid(node, cls.capabilities)
        return node


_REGISTRY: dict[str, type[Dialect]] = {}


def register(dialect: type[Dialect]) -> type[Dialect]:
    _REGISTRY[dialect.name.lower()] = dialect
    for alias in dialect.aliases:
        _REGISTRY[alias.lower()] = dialect
    return dialect


def get_dialect(name: str | None = None) -> Dialect:
    if name is None:
        name = "opencypher"
    key = name.lower()
    if key not in _REGISTRY:
        import cypherast.dialects  # noqa: F401
    if key not in _REGISTRY:
        raise ValueError(f"Unknown dialect: {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[key]()


def get_dialect_cls(name: str | None = None) -> type[Dialect]:
    get_dialect(name)  # ensure loaded
    key = (name or "opencypher").lower()
    if key not in _REGISTRY:
        raise ValueError(f"Unknown dialect: {name!r}")
    return _REGISTRY[key]


def dialect_names() -> list[str]:
    get_dialect()
    return sorted({d.name for d in _REGISTRY.values()})
