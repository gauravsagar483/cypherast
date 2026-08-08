"""Named optimizer rule registry (enable / disable by name)."""

from __future__ import annotations

import inspect
import typing as t
from collections.abc import Iterable, Sequence

from cypherast import ast as a

RuleFn = t.Callable[..., a.AstNode]


class Rule:
    """A named AST rewrite: ``(tree, **kwargs) -> tree``."""

    __slots__ = ("name", "fn")

    def __init__(self, name: str, fn: RuleFn) -> None:
        self.name = name
        self.fn = fn

    def __call__(self, tree: a.AstNode, **kwargs: t.Any) -> a.AstNode:
        params = inspect.signature(self.fn).parameters
        call_kwargs = {k: v for k, v in kwargs.items() if k in params}
        return self.fn(tree, **call_kwargs)

    def __repr__(self) -> str:
        return f"Rule({self.name!r})"


def rule(name: str | None = None) -> t.Callable[[RuleFn], Rule]:
    """Decorator: ``@rule()`` or ``@rule("pushdown")`` → ``Rule``."""

    def deco(fn: RuleFn) -> Rule:
        return Rule(name or fn.__name__, fn)

    return deco


class RuleSet:
    """Ordered sequence of named rules with ``only`` / ``disable`` filters."""

    def __init__(self, rules: Sequence[Rule | RuleFn] | None = None) -> None:
        self._rules: list[Rule] = []
        for r in rules or []:
            self._rules.append(r if isinstance(r, Rule) else Rule(r.__name__, r))

    def __iter__(self) -> t.Iterator[Rule]:
        return iter(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    def __add__(self, other: RuleSet | Sequence[Rule | RuleFn]) -> RuleSet:
        extra = other if isinstance(other, RuleSet) else RuleSet(other)
        return RuleSet([*self._rules, *extra._rules])

    def __repr__(self) -> str:
        return f"RuleSet([{', '.join(r.name for r in self._rules)}])"

    @property
    def names(self) -> list[str]:
        return [r.name for r in self._rules]

    def get(self, name: str) -> Rule:
        for r in self._rules:
            if r.name == name:
                return r
        raise KeyError(f"Unknown rule {name!r}. Known: {self.names}")

    def only(self, *names: str) -> RuleSet:
        """Keep only these rules (caller order preserved)."""
        wanted = set(names)
        unknown = wanted - set(self.names)
        if unknown:
            raise KeyError(f"Unknown rule(s) {sorted(unknown)}. Known: {self.names}")
        if not names:
            return RuleSet([])
        by_name = {r.name: r for r in self._rules}
        return RuleSet([by_name[n] for n in names])

    def disable(self, *names: str) -> RuleSet:
        """Drop these rules (alias: ``except_``)."""
        drop = set(names)
        unknown = drop - set(self.names)
        if unknown:
            raise KeyError(f"Unknown rule(s) {sorted(unknown)}. Known: {self.names}")
        return RuleSet([r for r in self._rules if r.name not in drop])

    except_ = disable

    def apply(
        self,
        tree: a.AstNode,
        *,
        copy: bool = True,
        schema: object | None = None,
        **kwargs: t.Any,
    ) -> a.AstNode:
        """Run all rules in order."""
        node = tree.copy() if copy else tree
        kw = {"schema": schema, **kwargs}
        for r in self._rules:
            node = r(node, **kw)
        return node


def resolve_rules(
    base: RuleSet,
    *,
    rules: RuleSet | Sequence[Rule | RuleFn] | None = None,
    only: Iterable[str] | None = None,
    disable: Iterable[str] | None = None,
) -> RuleSet:
    """Pick rule list: explicit ``rules``, else ``base`` filtered by only/disable."""
    rs = (rules if isinstance(rules, RuleSet) else RuleSet(rules)) if rules is not None else base
    if only is not None:
        rs = rs.only(*only)
    if disable is not None:
        rs = rs.disable(*disable)
    return rs
