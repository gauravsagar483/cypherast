"""Expression evaluation environment (Cypher null / 3VL aware)."""

from __future__ import annotations

import math
import random
import time
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
        return _arith(
            eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x + y
        )
    if isinstance(node, a.Sub):
        return _arith(
            eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x - y
        )
    if isinstance(node, a.Mul):
        return _arith(
            eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x * y
        )
    if isinstance(node, a.Div):
        return _arith(
            eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x / y
        )
    if isinstance(node, a.Mod):
        return _arith(
            eval_expr(node.this, env), eval_expr(node.expression, env), lambda x, y: x % y
        )
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
    if isinstance(node, a.Xor):
        l = cypher_true(eval_expr(node.this, env))
        r = cypher_true(eval_expr(node.expression, env))
        if l is None or r is None:
            return NULL
        return l != r
    if isinstance(node, a.Pow):
        base = eval_expr(node.this, env)
        exp = eval_expr(node.expression, env)
        if is_null(base) or is_null(exp):
            return NULL
        return base**exp
    if isinstance(node, a.Case):
        if node.this is not None:
            val = eval_expr(node.this, env)
            for cond, then in node.ifs:
                hit = _cmp(val, eval_expr(cond, env), lambda x, y: x == y)
                if hit is True:
                    return eval_expr(then, env)
                if hit is None:
                    return NULL
        else:
            for cond, then in node.ifs:
                if cypher_true(eval_expr(cond, env)) is True:
                    return eval_expr(then, env)
        if node.default is not None:
            return eval_expr(node.default, env)
        return NULL
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
        return _str_op(
            eval_expr(node.this, env), eval_expr(node.expression, env), lambda a, b: b in a
        )
    if isinstance(node, a.IsNull):
        v = is_null(eval_expr(node.this, env))
        return (not v) if node.not_ else v
    if isinstance(node, a.Quantifier):
        return _eval_quantifier(node, env)
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
    if isinstance(node, a.ListSlice):
        seq = eval_expr(node.this, env)
        if is_null(seq):
            return NULL
        start = 0 if node.start is None else int(eval_expr(node.start, env))
        if node.end is None:
            return seq[start:]
        end = int(eval_expr(node.end, env))
        return seq[start:end]
    if isinstance(node, a.LabelPredicate):
        obj = eval_expr(node.this, env)
        if is_null(obj):
            return NULL
        labels = node.labels.labels if isinstance(node.labels, a.LabelExpression) else []
        if isinstance(obj, Node):
            return all(lab in obj.labels for lab in (labels or []))
        if isinstance(obj, Relationship):
            rel_type = obj.type
            return rel_type in (labels or []) if labels else True
        return False
    if isinstance(node, a.MapProjection):
        base = eval_expr(node.this, env)
        if is_null(base):
            return NULL
        proj: dict[str, t.Any] = {}
        for entry in node.entries:
            if isinstance(entry, a.Star):
                if isinstance(base, (Node, Relationship)):
                    proj.update(base.props)
                elif isinstance(base, dict):
                    proj.update(base)
            elif isinstance(entry, a.PropertySelector):
                key = entry.name
                if isinstance(base, (Node, Relationship)):
                    proj[key] = base.props.get(key, NULL)
                elif isinstance(base, dict):
                    proj[key] = base.get(key, NULL)
                else:
                    proj[key] = NULL
            elif isinstance(entry, tuple):
                proj[entry[0]] = eval_expr(entry[1], env)
        return proj
    if isinstance(node, a.ListComprehension):
        src = eval_expr(node.source, env)
        if is_null(src):
            return NULL
        items: list[t.Any] = []
        for item in src:
            inner = env.bind(node.variable.this, item)
            if node.where is not None:
                w = cypher_true(eval_expr(node.where, inner))
                if w is not True:
                    continue
            items.append(eval_expr(node.projection, inner) if node.projection else item)
        return items
    if isinstance(node, a.PatternComprehension):
        from cypherast.executor.engine import Engine

        eng = Engine(env.graph, {})
        pat = node.pattern
        if isinstance(pat, a.PathPattern):
            pattern = a.Pattern(paths=[pat])
        elif isinstance(pat, a.Pattern):
            pattern = pat
        else:
            raise ExecuteError("Invalid pattern comprehension", code="CG1702")
        rows = eng._match_pattern(pattern, dict(env.bindings))
        comp_out: list[t.Any] = []
        for row in rows:
            inner = Env(env.graph, {**env.bindings, **row})
            if node.variable:
                inner = inner.bind(node.variable.this, row.get(node.variable.this))
            if node.where is not None:
                w = cypher_true(eval_expr(node.where, inner))
                if w is not True:
                    continue
            comp_out.append(eval_expr(node.projection, inner))
        return comp_out
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
            pattern = a.Pattern(paths=[pat]) if isinstance(pat, a.PathPattern) else pat
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


def _eval_quantifier(node: a.Quantifier, env: Env) -> t.Any:
    src = eval_expr(node.source, env)
    if is_null(src):
        return NULL
    if not isinstance(src, list):
        src = list(src)
    name = node.name.lower()
    if name == "all":
        for item in src:
            inner = env.bind(node.variable.this, item)
            if node.where is not None:
                if not cypher_true(eval_expr(node.where, inner)):
                    return False
            elif not item:
                return False
        return True
    if name == "any":
        for item in src:
            inner = env.bind(node.variable.this, item)
            if node.where is None or cypher_true(eval_expr(node.where, inner)):
                return True
        return False
    if name == "none":
        for item in src:
            inner = env.bind(node.variable.this, item)
            if node.where is None or cypher_true(eval_expr(node.where, inner)):
                return False
        return True
    if name == "single":
        found: t.Any = NULL
        count = 0
        for item in src:
            inner = env.bind(node.variable.this, item)
            if node.where is None or cypher_true(eval_expr(node.where, inner)):
                count += 1
                found = item
                if count > 1:
                    return NULL
        return found if count == 1 else NULL
    raise ExecuteError(f"Unknown quantifier {node.name!r}", code="CG1701")


def _call(node: a.FunctionCall, env: Env) -> t.Any:
    name = node.name.lower()
    args = [eval_expr(e, env) for e in node.expressions]
    if name == "length":
        v = args[0]
        if is_null(v):
            return NULL
        if isinstance(v, list):
            return sum(1 for x in v if isinstance(x, Relationship))
        if isinstance(v, str):
            return len(v)
        return NULL
    if name in ("nodes", "relationships", "rels"):
        v = args[0]
        if is_null(v) or not isinstance(v, list):
            return NULL
        cls = Node if name == "nodes" else Relationship
        return [x for x in v if isinstance(x, cls)]
    if name == "startnode":
        v = args[0]
        if is_null(v) or not isinstance(v, list) or not v:
            return NULL
        for item in v:
            if isinstance(item, Node):
                return item
        return NULL
    if name == "endnode":
        v = args[0]
        if is_null(v) or not isinstance(v, list) or not v:
            return NULL
        for item in reversed(v):
            if isinstance(item, Node):
                return item
        return NULL
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
    if name == "ceil":
        v = args[0]
        return NULL if is_null(v) else math.ceil(v)
    if name == "floor":
        v = args[0]
        return NULL if is_null(v) else math.floor(v)
    if name == "round":
        v = args[0]
        return NULL if is_null(v) else round(v)
    if name == "sqrt":
        v = args[0]
        return NULL if is_null(v) else math.sqrt(v)
    if name == "sign":
        v = args[0]
        if is_null(v):
            return NULL
        return 1 if v > 0 else -1 if v < 0 else 0
    if name == "exp":
        v = args[0]
        return NULL if is_null(v) else math.exp(v)
    if name == "log":
        v = args[0]
        return NULL if is_null(v) else math.log(v)
    if name == "log10":
        v = args[0]
        return NULL if is_null(v) else math.log10(v)
    if name == "e":
        return math.e
    if name == "pi":
        return math.pi
    if name == "rand":
        return random.random()
    if name == "timestamp":
        return int(time.time() * 1000)
    if name == "sin":
        v = args[0]
        return NULL if is_null(v) else math.sin(v)
    if name == "cos":
        v = args[0]
        return NULL if is_null(v) else math.cos(v)
    if name == "tan":
        v = args[0]
        return NULL if is_null(v) else math.tan(v)
    if name == "acos":
        v = args[0]
        return NULL if is_null(v) else math.acos(v)
    if name == "asin":
        v = args[0]
        return NULL if is_null(v) else math.asin(v)
    if name == "atan":
        v = args[0]
        return NULL if is_null(v) else math.atan(v)
    if name == "atan2":
        y, x = args[0], args[1]
        if is_null(y) or is_null(x):
            return NULL
        return math.atan2(y, x)
    if name == "cot":
        v = args[0]
        if is_null(v):
            return NULL
        return 1 / math.tan(v)
    if name == "degrees":
        v = args[0]
        return NULL if is_null(v) else math.degrees(v)
    if name == "radians":
        v = args[0]
        return NULL if is_null(v) else math.radians(v)
    if name == "left":
        s, n = args[0], args[1]
        if is_null(s) or is_null(n):
            return NULL
        return str(s)[: int(n)]
    if name == "right":
        s, n = args[0], args[1]
        if is_null(s) or is_null(n):
            return NULL
        n = int(n)
        return str(s)[-n:] if n else ""
    if name == "ltrim":
        v = args[0]
        return NULL if is_null(v) else str(v).lstrip()
    if name == "rtrim":
        v = args[0]
        return NULL if is_null(v) else str(v).rstrip()
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
