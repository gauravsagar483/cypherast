"""Validate capabilities + raise on remaining issues."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.dialects.validate.aggregates import (
    _collect_distinct_with_other_aggregates,
    _distinct_with_aggregate,
    _too_many_collect_distinct,
)
from cypherast.dialects.validate.cartesian import _cartesian_matches
from cypherast.dialects.validate.case_arms import _mismatched_case_arms
from cypherast.dialects.validate.exists_fn import _exists_function_calls
from cypherast.dialects.validate.id_predicates import _id_in_string_predicates
from cypherast.dialects.validate.issues import ConstraintIssue
from cypherast.dialects.validate.list_ops import (
    _list_concat_ops,
    _node_in_list_membership,
)
from cypherast.dialects.validate.nulls_order import _nulls_order_modifiers
from cypherast.dialects.validate.optional_scalar import _unguarded_optional_scalar_use
from cypherast.dialects.validate.pattern_predicates import _pattern_predicate_bindings
from cypherast.dialects.validate.schema_props import _schema_property_access
from cypherast.dialects.validate.undefined_vars import _undefined_variables
from cypherast.dialects.validate.union_columns import _union_column_mismatch
from cypherast.dialects.validate.unlabelled import _unlabelled_nodes
from cypherast.dialects.validate.var_length import _bad_var_length
from cypherast.errors import ValidationError
from cypherast.schema import ensure_schema


def validate_capabilities(
    tree: a.AstNode,
    caps: DialectCapabilities,
    *,
    schema: object | None = None,
) -> list[ConstraintIssue]:
    """Report remaining violations (after or instead of rewrite).

    Prefer ``optimize(..., write=dialect)`` then ``validate`` — raw validate
    may still flag constructs optimize rewrites (e.g. Cartesian MATCH).

    When ``schema`` is a ``GraphSchema``, also checks property access against
    declared labels/rel types (id-fields → CG1305; undeclared props when
    ``schema.strict`` → CG1303).
    """
    issues: list[ConstraintIssue] = []
    if caps.require_labelled_nodes:
        issues.extend(_unlabelled_nodes(tree))
    if not caps.allow_cartesian_match_paths:
        issues.extend(_cartesian_matches(tree))
    if caps.max_var_length_hops is not None or not caps.allow_unbounded_var_length:
        issues.extend(
            _bad_var_length(
                tree,
                max_hops=caps.max_var_length_hops or 5,
                allow_unbounded=caps.allow_unbounded_var_length,
            )
        )
    if not caps.allow_list_comprehension and tree.find(a.ListComprehension):
        issues.append(
            ConstraintIssue(
                "CG1401",
                "List comprehensions are not supported by this dialect",
                hint="Extract in WITH/MATCH, then collect(DISTINCT scalar) or count(DISTINCT …)",
            )
        )
    if not caps.allow_pattern_comprehension and tree.find(a.PatternComprehension):
        issues.append(
            ConstraintIssue(
                "CG1401",
                "Pattern comprehensions are not supported by this dialect",
                hint="Expand to MATCH / OPTIONAL MATCH + projection",
            )
        )
    if not caps.allow_list_concat:
        issues.extend(_list_concat_ops(tree))
    if not caps.allow_node_in_list_membership:
        issues.extend(_node_in_list_membership(tree))
    if not caps.allow_id_in_string_predicates:
        issues.extend(_id_in_string_predicates(tree))
    if not caps.allow_unguarded_optional_scalar_use:
        issues.extend(
            _unguarded_optional_scalar_use(
                tree, risky_functions=caps.optional_risky_functions
            )
        )
    if not caps.allow_mismatched_case_arms:
        issues.extend(_mismatched_case_arms(tree))
    if not caps.allow_nulls_order_modifiers:
        issues.extend(_nulls_order_modifiers(tree))
    if not caps.allow_exists_function:
        issues.extend(_exists_function_calls(tree))
    if not caps.allow_distinct_with_aggregate:
        issues.extend(_distinct_with_aggregate(tree))
    if caps.max_collect_distinct_per_clause is not None:
        issues.extend(
            _too_many_collect_distinct(tree, caps.max_collect_distinct_per_clause)
        )
    if not caps.allow_collect_distinct_with_other_aggregates:
        issues.extend(_collect_distinct_with_other_aggregates(tree))
    if caps.require_matching_union_columns:
        issues.extend(_union_column_mismatch(tree))
    if caps.check_undefined_variables:
        issues.extend(_undefined_variables(tree))
    if not caps.pattern_predicate_introduces_bindings:
        issues.extend(_pattern_predicate_bindings(tree))
    gs = ensure_schema(schema)
    if gs is not None:
        issues.extend(_schema_property_access(tree, gs))
    return issues


def raise_if_invalid(
    tree: a.AstNode,
    caps: DialectCapabilities,
    *,
    schema: object | None = None,
) -> None:
    issues = validate_capabilities(tree, caps, schema=schema)
    if not issues:
        return
    first = issues[0]
    raise ValidationError(
        first.message,
        code=first.code
        if first.code
        in {
            "CG1201",
            "CG1202",
            "CG1203",
            "CG1301",
            "CG1302",
            "CG1303",
            "CG1304",
            "CG1305",
            "CG1401",
            "CG1402",
        }
        else "CG1401",
        hint=first.hint or (f"+{len(issues) - 1} more" if len(issues) > 1 else None),
    )
