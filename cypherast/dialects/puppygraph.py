"""PuppyGraph dialect — openCypher 9 + engine capability constraints."""

from __future__ import annotations

import typing as t
from dataclasses import replace

from cypherast.dialects.capabilities import OPENCYPHER9_CAPABILITIES, DialectCapabilities
from cypherast.dialects.dialect import register
from cypherast.dialects.opencypher import OpenCypher, OpenCypherRenderer
from cypherast.renderer import Renderer


class PuppyGraphRenderer(OpenCypherRenderer):
    """Inherits openCypher bare pattern-predicate rendering."""

    dialect_name = "puppygraph"


@register
class PuppyGraph(OpenCypher):
    """PuppyGraph engine dialect (OC9 base + generic capability overrides)."""

    name = "puppygraph"
    aliases: t.ClassVar[list[str]] = ["puppy"]
    renderer_cls: t.ClassVar[type[Renderer]] = PuppyGraphRenderer
    capabilities: t.ClassVar[DialectCapabilities] = replace(
        OPENCYPHER9_CAPABILITIES,
        require_labelled_nodes=True,
        allow_cartesian_match_paths=False,
        rewrite_cartesian_match_paths=False,
        max_var_length_hops=None,
        allow_unbounded_var_length=True,
        rewrite_var_length_bounds=False,
        reject_var_length_binding=False,
        allow_list_comprehension=False,
        allow_pattern_comprehension=True,
        allow_list_concat=False,
        allow_node_in_list_membership=False,
        allow_id_in_string_predicates=False,
        allow_unguarded_optional_scalar_use=False,
        rewrite_unguarded_optional_scalar_use=True,
        optional_risky_functions=frozenset(
            {"id", "elementid", "split", "tostring", "tointeger", "tofloat", "size"}
        ),
        allow_mismatched_case_arms=False,
        max_collect_distinct_per_clause=1,
        rewrite_collect_distinct_cap=False,
        allow_collect_distinct_with_other_aggregates=False,
        allow_distinct_with_aggregate=False,
        rewrite_distinct_beside_aggregate=False,
        allow_mixed_aggregate_projection=False,
        allow_nulls_order_modifiers=False,
        require_matching_union_columns=True,
        pattern_predicate_introduces_bindings=False,
    )
