"""Expression evaluation environment (Cypher null / 3VL aware)."""

from __future__ import annotations

import typing as t

from cypherast import ast as a
from cypherast.errors import ExecuteError
from cypherast.executor.graph import Graph, Node, Relationship

# Sentinel for Cypher NULL
NULL = object()


def is_null(v: t.Any) -> bool:
    return v is NULL or v is None


def cypher_true(v: t.Any) -> bool | None:
    """3VL: True/False/None(unknown)."""
    if is_null(v):
        return None
    if isinstance(v, bool):
        return v
    return bool(v)


class Env:
    def __init__(self, graph: Graph, bindings: dict[str, t.Any] | None = None) -> None:
        self.graph = graph
        self.bindings: dict[str, t.Any] = dict(bindings or {})

    def bind(self, name: str, value: t.Any) -> Env:
        child = Env(self.graph, self.bindings)
        child.bindings[name] = value
        return child

    def eval(self, node: a.AstNode) -> t.Any:
        return eval_expr(node, self)


def eval_expr(node: a.AstNode, env: Env) -> t.Any:
    if isinstance(node, a.Null):
        return NULL
    if isinstance(node, a.Boolean):
        return node.this
    if isinstance(node, a.Integer):
        return node.this
    if isinstance(node, a.Float):
        return node.this
    if isinstance(node, a.String):
        return node.this
    if isinstance(node, a.Parameter):
        if node.name not in env.bindings:
            raise ExecuteError(f"Missing parameter ${node.name}", code="CG1704")
        return env.bindings[node.name]
    if isinstance(node, a.Identifier):
        if node.this not in env.bindings:
            raise ExecuteError(f"Unknown variable {node.this}", code="CG1702")
        return env.bindings[node.this]
    if isinstance(node, a.Property):
        obj = eval_expr(node.this, env)
        if is_null(obj):
            return NULL
        if isinstance(obj, (Node, Relationship)):
            return obj.props.get(node.name, NULL)
        if isinstance(obj, dict):
            return obj.get(node.name, NULL)
        raise ExecuteError(f"Cannot access property on {type(obj)}", code="CG1701")
    if isinstance(node, a.List):
        return [eval_expr(e, env) for e in node.expressions]
    if isinstance(node, a.Map):
        return {k: eval_expr(v, env) for k, v in node.entries}
    if isinstance(node, a.Add):
        return _arith(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x + y)
    if isinstance(node, a.Sub):
        return _arith(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x - y)
    if isinstance(node, a.Mul):
        return _arith(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x * y)
    if isinstance(node, a.Div):
        return _arith(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x / y)
    if isinstance(node, a.Mod):
        return _arith(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x % y)
    if isinstance(node, a.Neg):
        v = eval_expr(node.this, env)
        return NULL if is_null(v) else -v
    if isinstance(node, a.EQ):
        return _cmp(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x == y)
    if isinstance(node, a.NEQ):
        return _cmp(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x != y)
    if isinstance(node, a.LT):
        return _cmp(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x < y)
    if isinstance(node, a.LTE):
        return _cmp(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x <= y)
    if isinstance(node, a.GT):
        return _cmp(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x > y)
    if isinstance(node, a.GTE):
        return _cmp(eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x >= y)
    if isinstance(node, a.And):
        l, r = cypher_true(eval_expr(node.this, env)), cypher_true(eval_expr(node.expression, env))
        if l is False or r is False:
            return False
        if l is None or r is None:
            return NULL
        return True
    if isinstance(node, a.Or):
        l, r = cypher_true(eval_expr(node.this, env)), cypher_true(eval_expr(node.expression, env))
        if l is True or r is True:
            return True
        if l is None or r is None:
            return NULL
        return False
    if isinstance(node, a.Not):
        v = cypher_true(eval_expr(node.this, env))
        if v is None:
            return NULL
        return not v
    if isinstance(node, a.In):
        left = eval_expr(node.this, env)
        right = eval_expr(node.expression, env)
        if is_null(left) or is_null(right):
            return NULL
        return left in right
    if isinstance(node, a.StartsWith):
        return _str_op(eval_expr(node.this, env), eval_expr(node.expression, env), str.startswith)
    if isinstance(node, a.EndsWith):
        return _str_op(eval_expr(node.this, env), eval_expr(node.expression, env), str.endswith)
    if isinstance(node, a.Contains):
        return _str_op(eval_expr(node.this, env), eval_expr(node.expression, env), lambda a, b: b in a)
    if isinstance(node, a.IsNull):
        v = is_null(eval_expr(node.this, env))
        return (not v) if node.not_ else v
    if isinstance(node, a.FunctionCall):
        return _call(node, env)
    if isinstance(node, a.Coalesce):
        for e in node.expressions:
            v = eval_expr(e, env)
            if not is_null(v):
                return v
        return NULL
    if isinstance(node, a.ListSubscript):
        seq = eval_expr(node.this, env)
        idx = eval_expr(node.index, env)
        if is_null(seq) or is_null(idx):
            return NULL
        try:
            return seq[int(idx)]
        except (IndexError, TypeError, KeyError) as e:
            raise ExecuteError(f"List subscript error: {e}", code="CG1701") from e
    if isinstance(node, a.PatternPredicate):
        # Evaluate via mini match from current bindings
        from cypherast.executor.engine import Engine

        eng = Engine(env.graph, {})
        pat = node.pattern
        if isinstance(pat, a.Cypher):
            pat = pat.this
        if isinstance(pat, a.Query):
            # EXISTS { query } — true if inner produces ≥1 row
            try:
                result = eng.run_query(pat)
                exists = len(result.rows) > 0
            except ExecuteError:
                exists = False
        else:
            pattern = (
                a.Pattern(paths=[pat])
                if isinstance(pat, a.PathPattern)
                else pat
            )
            assert isinstance(pattern, a.Pattern)
            rows = eng._match_pattern(pattern, dict(env.bindings))
            exists = len(rows) > 0
        return (not exists) if node.not_ else exists
    if isinstance(node, a.Alias):
        return eval_expr(node.this, env)
    if isinstance(node, a.Star):
        return {k: v for k, v in env.bindings.items()}
    raise ExecuteError(f"Cannot evaluate {type(node).__name__}", code="CG1702")


def _arith(a: t.Any, b: t.Any, op: t.Callable[[t.Any, t.Any], t.Any]) -> t.Any:
    if is_null(a) or is_null(b):
        return NULL
    return op(a, b)


def _cmp(a: t.Any, b: t.Any, op: t.Callable[[t.Any, t.Any], bool]) -> t.Any:
    if is_null(a) or is_null(b):
        return NULL
    return op(a, b)


def _str_op(a: t.Any, b: t.Any, op: t.Callable[[str, str], bool]) -> t.Any:
    if is_null(a) or is_null(b):
        return NULL
    return op(str(a), str(b))


def _call(node: a.FunctionCall, env: Env) -> t.Any:
    name = node.name.lower()
    args = [eval_expr(e, env) for e in node.expressions]
    if name == "size":
        v = args[0]
        return NULL if is_null(v) else len(v)
    if name == "tostring":
        v = args[0]
        return NULL if is_null(v) else str(v)
    if name == "tolower":
        v = args[0]
        return NULL if is_null(v) else str(v).lower()
    if name == "toupper":
        v = args[0]
        return NULL if is_null(v) else str(v).upper()
    if name == "trim":
        v = args[0]
        return NULL if is_null(v) else str(v).strip()
    if name == "replace":
        s, old, new = args[0], args[1], args[2]
        if is_null(s) or is_null(old) or is_null(new):
            return NULL
        return str(s).replace(str(old), str(new))
    if name == "split":
        s, sep = args[0], args[1]
        if is_null(s) or is_null(sep):
            return NULL
        return str(s).split(str(sep))
    if name == "substring":
        s = args[0]
        if is_null(s):
            return NULL
        start = int(args[1])
        if len(args) > 2 and not is_null(args[2]):
            return str(s)[start : start + int(args[2])]
        return str(s)[start:]
    if name == "tointeger":
        v = args[0]
        return NULL if is_null(v) else int(v)
    if name == "tofloat":
        v = args[0]
        return NULL if is_null(v) else float(v)
    if name == "toboolean":
        v = args[0]
        if is_null(v):
            return NULL
        if isinstance(v, bool):
            return v
        return str(v).lower() in {"true", "1", "yes"}
    if name == "abs":
        v = args[0]
        return NULL if is_null(v) else abs(v)
    if name == "coalesce":
        for v in args:
            if not is_null(v):
                return v
        return NULL
    if name == "head":
        v = args[0]
        return NULL if is_null(v) or not v else v[0]
    if name == "last":
        v = args[0]
        return NULL if is_null(v) or not v else v[-1]
    if name == "tail":
        v = args[0]
        return NULL if is_null(v) else list(v[1:])
    if name == "range":
        start, end = int(args[0]), int(args[1])
        step = int(args[2]) if len(args) > 2 else 1
        return list(range(start, end + 1, step))
    if name == "reverse":
        v = args[0]
        if is_null(v):
            return NULL
        return list(reversed(v)) if isinstance(v, list) else str(v)[::-1]
    if name == "labels":
        v = args[0]
        return NULL if is_null(v) else sorted(v.labels) if isinstance(v, Node) else NULL
    if name == "type":
        v = args[0]
        return NULL if is_null(v) else (v.type if isinstance(v, Relationship) else NULL)
    if name == "id":
        v = args[0]
        return NULL if is_null(v) else getattr(v, "id", NULL)
    if name == "elementid":
        v = args[0]
        if is_null(v):
            return NULL
        if isinstance(v, Node):
            labs = list(v.labels) or ["node"]
            return f"{labs[0]}[v{v.id}]"
        if isinstance(v, Relationship):
            return f"{v.type}[e{v.id}]"
        return str(v)
    if name == "keys":
        v = args[0]
        if is_null(v):
            return NULL
        if isinstance(v, (Node, Relationship)):
            return list(v.props.keys())
        if isinstance(v, dict):
            return list(v.keys())
    if name == "properties":
        v = args[0]
        if is_null(v):
            return NULL
        if isinstance(v, (Node, Relationship)):
            return dict(v.props)
    raise ExecuteError(f"Unknown function {node.name}", code="CG1702")
