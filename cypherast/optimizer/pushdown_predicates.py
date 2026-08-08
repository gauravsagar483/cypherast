"""Push predicates: fold WHERE n.x = lit into node properties when safe."""

from __future__ import annotations

from cypherast import ast as a


def pushdown_predicates(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    def _fix(node: a.AstNode) -> a.AstNode | None:
        if not isinstance(node, a.Match) or node.where is None:
            return node
        pred = node.where.this
        remaining, folded = _try_fold(pred, node.pattern)
        if folded:
            node.where = a.Where(this=remaining) if remaining is not None else None
        return node

    return tree.transform(_fix, copy=False)


def _try_fold(pred: a.AstNode, pattern: a.Pattern) -> tuple[a.AstNode | None, bool]:
    if isinstance(pred, a.And):
        left, f1 = _try_fold(pred.this, pattern)
        right, f2 = _try_fold(pred.expression, pattern)
        if left is None:
            return right, f1 or f2
        if right is None:
            return left, f1 or f2
        return a.And(this=left, expression=right), f1 or f2

    # n.prop = literal
    if (
        isinstance(pred, a.EQ)
        and isinstance(pred.this, a.Property)
        and isinstance(pred.this.this, a.Identifier)
        and isinstance(pred.expression, (a.Integer, a.Float, a.String, a.Boolean))
    ):
        var = pred.this.this.this
        prop = pred.this.name
        if _inject_prop(pattern, var, prop, pred.expression):
            return None, True

    # toLower(n.prop) = 'lit' → still fold property equality on original (planner hint;
    # keep predicate but also inject if exact-case literal matches common pattern)
    if (
        isinstance(pred, a.EQ)
        and isinstance(pred.this, a.FunctionCall)
        and pred.this.name.lower() == "tolower"
        and pred.this.expressions
        and isinstance(pred.this.expressions[0], a.Property)
        and isinstance(pred.expression, a.String)
    ):
        # Do not inject (casefold); leave WHERE — annotate via comment on node type only
        return pred, False

    return pred, False


def _inject_prop(pattern: a.Pattern, var: str, prop: str, value: a.AstNode) -> bool:
    for path in pattern.paths:
        for el in path.elements:
            if (
                isinstance(el, a.NodePattern)
                and isinstance(el.variable, a.Identifier)
                and el.variable.this == var
            ):
                entries = list(el.properties.entries) if isinstance(el.properties, a.Map) else []
                if any(k == prop for k, _ in entries):
                    return False
                entries.append((prop, value))
                el.properties = a.Map(entries=entries)
                return True
    return False
