"""Constant folding + boolean/arith simplify (Cypher null / 3VL aware)."""

from __future__ import annotations

import typing as t

from cypherast import ast as a


def _is_null(n: a.AstNode) -> bool:
    return isinstance(n, a.Null)


def _as_bool(n: a.AstNode) -> bool | None:
    if isinstance(n, a.Boolean):
        return bool(n.this)
    return None


def _as_num(n: a.AstNode) -> int | float | None:
    if isinstance(n, a.Integer):
        return int(n.this)
    if isinstance(n, a.Float):
        return float(n.this)
    return None


def simplify(tree: a.AstNode, schema: object | None = None) -> a.AstNode:
    def _fix(node: a.AstNode) -> a.AstNode | None:
        if isinstance(node, a.Not):
            b = _as_bool(node.this)
            if b is not None:
                return a.Boolean(this=not b)
            if _is_null(node.this):
                return a.Null()
        if isinstance(node, a.And):
            l, r = _as_bool(node.this), _as_bool(node.expression)
            if l is False or r is False:
                return a.Boolean(this=False)
            if l is True:
                return t.cast(a.AstNode, node.expression)
            if r is True:
                return t.cast(a.AstNode, node.this)
            if _is_null(node.this) or _is_null(node.expression):
                # 3VL: true AND null = null; false already handled
                if l is True:
                    return a.Null()
                if r is True:
                    return a.Null()
                if _is_null(node.this) and _is_null(node.expression):
                    return a.Null()
        if isinstance(node, a.Or):
            l, r = _as_bool(node.this), _as_bool(node.expression)
            if l is True or r is True:
                return a.Boolean(this=True)
            if l is False:
                return t.cast(a.AstNode, node.expression)
            if r is False:
                return t.cast(a.AstNode, node.this)
        if isinstance(node, a.Add):
            ln, rn = _as_num(node.this), _as_num(node.expression)
            if ln is not None and rn is not None:
                val = ln + rn
                return a.Float(this=val) if isinstance(val, float) else a.Integer(this=val)
            if _is_null(node.this) or _is_null(node.expression):
                return a.Null()
        if isinstance(node, a.Mul):
            ln, rn = _as_num(node.this), _as_num(node.expression)
            if ln is not None and rn is not None:
                val = ln * rn
                return a.Float(this=val) if isinstance(val, float) else a.Integer(this=val)
        if isinstance(node, a.EQ):
            if _is_null(node.this) or _is_null(node.expression):
                return a.Null()  # Cypher: null = x is null
            if isinstance(node.this, a.Integer) and isinstance(node.expression, a.Integer):
                return a.Boolean(this=node.this.this == node.expression.this)
        if isinstance(node, a.IsNull):
            if _is_null(node.this):
                return a.Boolean(this=not node.not_)
            if isinstance(node.this, (a.Integer, a.Float, a.String, a.Boolean)):
                return a.Boolean(this=bool(node.not_))
        return node

    return tree.transform(_fix, copy=False)
