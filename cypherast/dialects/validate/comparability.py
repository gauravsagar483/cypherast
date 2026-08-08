"""Comparability / orderability checks (openCypher 9, PDF pp. 25–34)."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue

_TypeCat = str

_COMPARABLE_PAIRS = frozenset(
    {
        ("boolean", "boolean"),
        ("integer", "integer"),
        ("float", "float"),
        ("integer", "float"),
        ("float", "integer"),
        ("number", "number"),
        ("string", "string"),
        ("list", "list"),
        ("map", "map"),
        ("node", "node"),
        ("relationship", "relationship"),
        ("path", "path"),
        ("null", "null"),
        ("unknown", "unknown"),
    }
)


def _type_cat(node: a.AstNode) -> _TypeCat:
    if isinstance(node, a.Null):
        return "null"
    if isinstance(node, a.Boolean):
        return "boolean"
    if isinstance(node, a.Integer):
        return "integer"
    if isinstance(node, a.Float):
        return "float"
    if isinstance(node, a.String):
        return "string"
    if isinstance(node, a.List):
        return "list"
    if isinstance(node, a.Map):
        return "map"
    if node.type:
        t_ = str(node.type).lower()
        if t_ in (
            "integer",
            "float",
            "string",
            "boolean",
            "list",
            "map",
            "node",
            "relationship",
            "path",
        ):
            return t_
    return "unknown"


def _pair_key(a_cat: _TypeCat, b_cat: _TypeCat) -> tuple[_TypeCat, _TypeCat]:
    if a_cat in ("integer", "float") and b_cat in ("integer", "float"):
        return ("number", "number")
    return (a_cat, b_cat)


def _orderable_ok(la: _TypeCat, rb: _TypeCat) -> bool:
    if la == "null" or rb == "null":
        return True
    if la in ("integer", "float") and rb in ("integer", "float"):
        return True
    return la == "string" and rb == "string"


def _comparability_issues(
    left: a.AstNode,
    right: a.AstNode,
    *,
    orderable: bool,
) -> list[ConstraintIssue]:
    la, rb = _type_cat(left), _type_cat(right)
    if la == "unknown" or rb == "unknown":
        return []
    if la == "null" or rb == "null":
        return []
    key = _pair_key(la, rb)
    if orderable:
        if not _orderable_ok(la, rb):
            return [
                ConstraintIssue(
                    "CG1512",
                    f"Values of type {la!r} and {rb!r} are not orderable",
                    hint="Use = or <> for equality; ordering requires numbers or strings",
                )
            ]
        return []
    if key not in _COMPARABLE_PAIRS:
        return [
            ConstraintIssue(
                "CG1512",
                f"Values of type {la!r} and {rb!r} are not comparable",
                hint="Check operand types for = or <>",
            )
        ]
    return []


def _walk_comparisons(node: a.AstNode) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    for n in node.walk():
        if isinstance(n, (a.EQ, a.NEQ)):
            issues.extend(_comparability_issues(n.this, n.expression, orderable=False))
        elif isinstance(n, (a.LT, a.LTE, a.GT, a.GTE)):
            issues.extend(_comparability_issues(n.this, n.expression, orderable=True))
    return issues


def comparability_issues(tree: a.AstNode) -> list[ConstraintIssue]:
    return _walk_comparisons(tree)
