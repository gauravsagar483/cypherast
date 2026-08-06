"""PuppyGraph dialect — openCypher 9 + engine capability constraints."""

from __future__ import annotations

import typing as t

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.dialects.dialect import register
from cypherast.dialects.opencypher import OpenCypher, OpenCypherRenderer
from cypherast.renderer import Renderer


class PuppyGraphRenderer(OpenCypherRenderer):
    """Inherits openCypher rendering; override only PuppyGraph deltas."""

    dialect_name = "puppygraph"

    def render_PatternPredicate(self, node: a.PatternPredicate) -> str:
        # No exists() function — emit bare pattern predicates only.
        body = self.dispatch(node.pattern)
        if isinstance(node.pattern, (a.Query, a.Union, a.Cypher)):
            text = f"EXISTS {{ {body} }}"
            return f"NOT {text}" if node.not_ else text
        if isinstance(node.pattern, a.PathPattern):
            return f"NOT ({body})" if node.not_ else f"({body})"
        return f"NOT {body}" if node.not_ else body


@register
class PuppyGraph(OpenCypher):
    """PuppyGraph engine dialect (generic capability overrides — no domain schema)."""

    name = "puppygraph"
    aliases: t.ClassVar[list[str]] = ["puppy"]
    renderer_cls: t.ClassVar[type[Renderer]] = PuppyGraphRenderer
    capabilities: t.ClassVar[DialectCapabilities] = DialectCapabilities(
        require_labelled_nodes=True,
        allow_cartesian_match_paths=False,
        # Leave var-length alone (incl. unbounded *); callers bound hops if needed.
        max_var_length_hops=None,
        allow_unbounded_var_length=True,
        allow_exists_function=False,
        allow_list_comprehension=False,
        allow_pattern_comprehension=True,  # parse OK; prefer MATCH expand when possible
        allow_list_concat=False,
        allow_node_in_list_membership=False,
        max_collect_distinct_per_clause=1,
        allow_distinct_with_aggregate=False,
        allow_nulls_order_modifiers=False,
        require_limit_on_row_return=True,
        default_row_limit=20,
        pattern_predicate_introduces_bindings=False,
    )
