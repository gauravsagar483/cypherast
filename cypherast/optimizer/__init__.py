"""Optimizer entrypoint — named rules with enable/disable."""

from __future__ import annotations

import typing as t
from collections.abc import Iterable, Sequence

from cypherast import ast as a
from cypherast.optimizer.catalog import (
    ALL_CANONICAL_RULES,
    OPTIONAL_RULES,
    RULES,
    constraint_rules,
)
from cypherast.optimizer.engine import Rule, RuleFn, RuleSet, resolve_rules, rule

__all__ = [
    "ALL_CANONICAL_RULES",
    "OPTIONAL_RULES",
    "RULES",
    "Rule",
    "RuleFn",
    "RuleSet",
    "constraint_rules",
    "optimize",
    "resolve_rules",
    "rule",
]


def optimize(
    tree: a.AstNode,
    schema: object | None = None,
    *,
    rules: RuleSet | Sequence[Rule | RuleFn] | None = None,
    only: Iterable[str] | None = None,
    disable: Iterable[str] | None = None,
    constraints: RuleSet | Sequence[Rule | RuleFn] | None = None,
    constraint_only: Iterable[str] | None = None,
    constraint_disable: Iterable[str] | None = None,
    copy: bool = True,
    **kwargs: t.Any,
) -> a.AstNode:
    """Apply canonicalizer rules, then optional constraint rules.

    Examples::

        from cypherast.optimizer import RULES, optimize

        optimize(tree)  # default RULES
        optimize(tree, disable=["qualify", "annotate_types"])
        optimize(tree, only=["simplify", "pushdown_predicates"])
        optimize(tree, rules=RULES + OPTIONAL_RULES)
        optimize(tree, constraints=constraint_rules(caps), constraint_disable=["strip_nulls_order_modifiers"])
    """
    canon = resolve_rules(RULES, rules=rules, only=only, disable=disable)
    node = canon.apply(tree, copy=copy, schema=schema, **kwargs)

    if constraints is not None:
        cons = resolve_rules(
            constraints if isinstance(constraints, RuleSet) else RuleSet(constraints),
            only=constraint_only,
            disable=constraint_disable,
        )
        if len(cons):
            node = cons.apply(node, copy=False, schema=schema, **kwargs)
    return node
