"""IR canonicalizer rewriter passes (back-compat re-exports from optimizer)."""

from __future__ import annotations

import typing as t
from collections.abc import Iterable, Sequence

from cypherast import ast as a
from cypherast.optimizer.annotate_types import annotate_types
from cypherast.optimizer.canonicalize_patterns import canonicalize_patterns
from cypherast.optimizer.merge_match_chains import merge_match_chains
from cypherast.optimizer.pushdown_predicates import pushdown_predicates
from cypherast.optimizer.qualify import qualify
from cypherast.optimizer.simplify import simplify

if t.TYPE_CHECKING:
    from cypherast.optimizer.engine import RuleSet

__all__ = [
    "RULES",
    "annotate_types",
    "canonicalize_patterns",
    "merge_match_chains",
    "optimize",
    "pushdown_predicates",
    "qualify",
    "simplify",
]

RuleCallable = t.Callable[..., a.AstNode]

# Back-compat callable list (order matches optimizer.RULES)
RULES: list[RuleCallable] = [
    qualify,
    canonicalize_patterns,
    simplify,
    pushdown_predicates,
    annotate_types,
]


def optimize(
    tree: a.AstNode,
    schema: object | None = None,
    rules: Sequence[RuleCallable] | RuleSet | None = None,
    *,
    only: Iterable[str] | None = None,
    disable: Iterable[str] | None = None,
) -> a.AstNode:
    """Apply rewriter passes. Prefer ``cypherast.optimizer.optimize`` for RuleSet API."""
    from cypherast.optimizer import RuleSet as RS
    from cypherast.optimizer import optimize as _opt_optimize

    if only is not None or disable is not None:
        return _opt_optimize(tree, schema=schema, rules=rules, only=only, disable=disable)
    if isinstance(rules, RS):
        return _opt_optimize(tree, schema=schema, rules=rules)
    if rules is not None:
        return _opt_optimize(tree, schema=schema, rules=RS(list(rules)))
    return _opt_optimize(tree, schema=schema)
