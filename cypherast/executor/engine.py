"""Pull-based Cypher executor over in-memory Graph."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from cypherast import ast as a
from cypherast.errors import ExecuteError
from cypherast.executor.env import NULL, Env, cypher_true, eval_expr, is_null
from cypherast.executor.graph import Graph, Node, Relationship


@dataclass
class Result:
    columns: list[str]
    rows: list[list[t.Any]] = field(default_factory=list)

    def __iter__(self) -> t.Iterator[dict[str, t.Any]]:
        for row in self.rows:
            yield {c: (None if v is NULL else v) for c, v in zip(self.columns, row, strict=False)}

    def __len__(self) -> int:
        return len(self.rows)


Row = dict[str, t.Any]


def execute(
    tree: a.AstNode,
    graph: Graph | None = None,
    schema: object | None = None,
    params: dict[str, t.Any] | None = None,
) -> Result:
    g = graph or Graph()
    query = tree.this if isinstance(tree, a.Cypher) else tree
    engine = Engine(g, params or {})
    if isinstance(query, a.Union):
        return engine.run_union(query)
    if isinstance(query, a.Query):
        return engine.run_query(query)
    raise ExecuteError(f"Cannot execute {type(query).__name__}", code="CG1702")


class Engine:
    def __init__(self, graph: Graph, params: dict[str, t.Any]) -> None:
        self.graph = graph
        self.params = params

    def run_union(self, node: a.Union) -> Result:
        left = self.run_query(node.this) if isinstance(node.this, a.Query) else execute(
            a.Cypher(this=node.this), self.graph, params=self.params
        )
        right = self.run_query(node.expression) if isinstance(node.expression, a.Query) else execute(
            a.Cypher(this=node.expression), self.graph, params=self.params
        )
        rows = list(left.rows) + list(right.rows)
        if node.distinct:
            seen: set[t.Any] = set()
            uniq = []
            for r in rows:
                key = tuple(_freeze(x) for x in r)
                if key not in seen:
                    seen.add(key)
                    uniq.append(r)
            rows = uniq
        return Result(columns=left.columns, rows=rows)

    def run_query(self, query: a.Query) -> Result:
        rows: list[Row] = [{}]
        result_cols: list[str] = []
        result_rows: list[list[t.Any]] = []

        for clause in query.clauses:
            if isinstance(clause, a.Match):
                rows = self._match(clause, rows)
            elif isinstance(clause, a.With):
                rows = self._project(clause, rows, is_with=True)
            elif isinstance(clause, a.Unwind):
                rows = self._unwind(clause, rows)
            elif isinstance(clause, a.Create):
                rows = self._create(clause, rows)
            elif isinstance(clause, a.Merge):
                rows = self._merge(clause, rows)
            elif isinstance(clause, a.Set):
                rows = self._set(clause, rows)
            elif isinstance(clause, a.Delete):
                rows = self._delete(clause, rows)
            elif isinstance(clause, a.Remove):
                rows = self._remove(clause, rows)
            elif isinstance(clause, a.Foreach):
                rows = self._foreach(clause, rows)
            elif isinstance(clause, a.CallSubquery):
                # Parse-tolerant: run inner query in isolation; keep outer rows
                inner = clause.query
                if isinstance(inner, a.Cypher):
                    inner = inner.this
                if isinstance(inner, a.Query):
                    self.run_query(inner)
                rows = rows
            elif isinstance(clause, a.Return):
                result_cols, result_rows = self._return(clause, rows)
                rows = []  # done
            else:
                raise ExecuteError(
                    f"Unsupported clause {type(clause).__name__}", code="CG1702"
                )
        return Result(columns=result_cols, rows=result_rows)

    def _env(self, row: Row) -> Env:
        env = Env(self.graph, {**self.params, **row})
        return env

    def _match(self, clause: a.Match, rows: list[Row]) -> list[Row]:
        out: list[Row] = []
        for row in rows:
            matches = self._match_pattern(clause.pattern, row)
            if not matches and clause.optional:
                # bind pattern vars to null
                null_row = dict(row)
                for var in _pattern_vars(clause.pattern):
                    null_row.setdefault(var, NULL)
                out.append(null_row)
            else:
                for m in matches:
                    merged = {**row, **m}
                    if clause.where is None or cypher_true(
                        eval_expr(clause.where.this, self._env(merged))
                    ):
                        out.append(merged)
        return out

    def _match_pattern(self, pattern: a.Pattern, row: Row) -> list[Row]:
        results: list[Row] = [dict(row)]
        for path in pattern.paths:
            next_results: list[Row] = []
            for r in results:
                next_results.extend(self._match_path(path, r))
            results = next_results
        return results

    def _match_path(self, path: a.PathPattern, row: Row) -> list[Row]:
        elems = path.elements
        if not elems:
            return [row]
        # Start with candidate nodes for first NodePattern
        first = elems[0]
        if not isinstance(first, a.NodePattern):
            raise ExecuteError("Path must start with node", code="CG1702")
        candidates = self._candidate_nodes(first, row)
        rows: list[Row] = []
        for node in candidates:
            r0 = dict(row)
            if first.variable:
                name = first.variable.this
                if name in r0 and r0[name] is not node and r0[name] is not NULL:
                    continue
                r0[name] = node
            rows.extend(self._expand(elems[1:], r0, node))
        return rows

    def _expand(
        self, elems: list[a.AstNode], row: Row, current: Node
    ) -> list[Row]:
        if not elems:
            return [row]
        if len(elems) == 1:
            # dangling — shouldn't happen; treat as done
            return [row]
        if len(elems) < 2:
            raise ExecuteError("Invalid path structure", code="CG1702")
        rel_pat = elems[0]
        node_pat = elems[1]
        rest = elems[2:]
        if not isinstance(rel_pat, a.RelationshipPattern) or not isinstance(
            node_pat, a.NodePattern
        ):
            raise ExecuteError("Invalid path structure", code="CG1702")

        rels = self._candidate_rels(rel_pat, current)
        out: list[Row] = []
        for rel, other in rels:
            if not self._node_matches(node_pat, other, row):
                continue
            r1 = dict(row)
            if rel_pat.variable:
                name = rel_pat.variable.this
                if name in r1 and r1[name] is not rel and r1[name] is not NULL:
                    continue
                r1[name] = rel
            if node_pat.variable:
                name = node_pat.variable.this
                if name in r1 and r1[name] is not other and r1[name] is not NULL:
                    continue
                r1[name] = other
            out.extend(self._expand(rest, r1, other))
        return out

    def _candidate_nodes(self, pat: a.NodePattern, row: Row) -> list[Node]:
        if pat.variable and pat.variable.this in row and isinstance(row[pat.variable.this], Node):
            n = row[pat.variable.this]
            return [n] if self._node_matches(pat, n, row) else []
        labels = pat.labels.labels if isinstance(pat.labels, a.LabelExpression) else []
        if labels:
            nodes = self.graph.nodes_with_label(labels[0])
            for lab in labels[1:]:
                nodes = [n for n in nodes if lab in n.labels]
        else:
            nodes = self.graph.all_nodes()
        return [n for n in nodes if self._node_matches(pat, n, row)]

    def _node_matches(self, pat: a.NodePattern, node: Node, row: Row) -> bool:
        labels = pat.labels.labels if isinstance(pat.labels, a.LabelExpression) else []
        if any(l not in node.labels for l in labels):
            return False
        if isinstance(pat.properties, a.Map):
            env = self._env(row)
            for k, vexpr in pat.properties.entries:
                expected = eval_expr(vexpr, env)
                actual = node.props.get(k, NULL)
                if is_null(expected) or is_null(actual) or expected != actual:
                    return False
        return True

    def _candidate_rels(
        self, pat: a.RelationshipPattern, current: Node
    ) -> list[tuple[Relationship, Node]]:
        types = pat.types
        typ = types[0] if types and len(types) == 1 else None
        out: list[tuple[Relationship, Node]] = []

        def add(rel: Relationship, other_id: int) -> None:
            if types and rel.type not in types:
                return
            other = self.graph.nodes.get(other_id)
            if other is None:
                return
            if isinstance(pat.properties, a.Map):
                for k, vexpr in pat.properties.entries:
                    # property filter on rel — literals only for now
                    from cypherast.executor.env import Env as _E

                    expected = eval_expr(vexpr, _E(self.graph, self.params))
                    if rel.props.get(k, NULL) != expected:
                        return
            out.append((rel, other))

        # Variable-length: BFS within hop bounds
        if pat.variable_length:
            min_h = pat.min_hops if pat.min_hops is not None else 1
            max_h = pat.max_hops if pat.max_hops is not None else 10
            out.extend(self._var_expand(current, pat, min_h, max_h))
            return out

        if pat.direction in (a.Direction.OUTGOING, a.Direction.BOTH):
            for rel in self.graph.out_rels(current.id, typ if typ else None):
                if not typ and types and rel.type not in types:
                    continue
                add(rel, rel.end)
        if pat.direction in (a.Direction.INCOMING, a.Direction.BOTH):
            for rel in self.graph.in_rels(current.id, typ if typ else None):
                if not typ and types and rel.type not in types:
                    continue
                add(rel, rel.start)
        return out

    def _var_expand(
        self,
        start: Node,
        pat: a.RelationshipPattern,
        min_h: int,
        max_h: int,
    ) -> list[tuple[Relationship, Node]]:
        # Return last hop rel + end node for paths of length in [min,max]
        # Simplified: yield (None-like last rel, end node) — use last relationship
        results: list[tuple[Relationship, Node]] = []
        # BFS: (node, depth, last_rel, visited_rels)
        from collections import deque

        q: deque[tuple[Node, int, Relationship | None, set[int]]] = deque(
            [(start, 0, None, set())]
        )
        while q:
            node, depth, last_rel, visited = q.popleft()
            if depth >= min_h and last_rel is not None:
                results.append((last_rel, node))
            if depth >= max_h:
                continue
            candidates: list[Relationship] = []
            if pat.direction in (a.Direction.OUTGOING, a.Direction.BOTH):
                candidates.extend(self.graph.out_rels(node.id))
            if pat.direction in (a.Direction.INCOMING, a.Direction.BOTH):
                candidates.extend(self.graph.in_rels(node.id))
            for rel in candidates:
                if rel.id in visited:
                    continue
                if pat.types and rel.type not in pat.types:
                    continue
                other_id = rel.end if rel.start == node.id else rel.start
                other = self.graph.nodes.get(other_id)
                if other is None:
                    continue
                q.append((other, depth + 1, rel, visited | {rel.id}))
        return results

    def _project(self, clause: a.With | a.Return, rows: list[Row], is_with: bool) -> list[Row]:
        projected: list[Row] = []
        for row in rows:
            env = self._env(row)
            new_row: Row = {}
            for expr in clause.expressions or []:
                if isinstance(expr, a.Star):
                    new_row.update(row)
                    continue
                val = eval_expr(expr, env)
                name = _proj_name(expr)
                new_row[name] = val
            projected.append(new_row)

        if clause.distinct:
            seen: set[t.Any] = set()
            uniq = []
            for r in projected:
                key = tuple(sorted((k, _freeze(v)) for k, v in r.items()))
                if key not in seen:
                    seen.add(key)
                    uniq.append(r)
            projected = uniq

        if getattr(clause, "where", None) is not None and is_with:
            projected = [
                r
                for r in projected
                if cypher_true(eval_expr(clause.where.this, self._env(r)))
            ]

        if getattr(clause, "order", None):
            for ordered in reversed(clause.order.expressions):
                assert isinstance(ordered, a.Ordered)

                def _key(
                    r: Row, o: a.Ordered = ordered
                ) -> tuple[int, t.Any]:
                    val = eval_expr(o.this, self._env(r))
                    null_first = 0 if is_null(val) else 1
                    null_last = 1 if is_null(val) else 0
                    return (
                        (null_first if o.desc else null_last),
                        _sort_val(val),
                    )

                projected.sort(key=_key, reverse=bool(ordered.desc))

        if getattr(clause, "skip", None):
            n = eval_expr(clause.skip.this, self._env({}))
            projected = projected[int(n) :]
        if getattr(clause, "limit", None):
            n = eval_expr(clause.limit.this, self._env({}))
            projected = projected[: int(n)]
        return projected

    def _return(self, clause: a.Return, rows: list[Row]) -> tuple[list[str], list[list[t.Any]]]:
        # Aggregation detection
        has_agg = any(_is_agg(e) for e in (clause.expressions or []))
        if has_agg:
            return self._aggregate_return(clause, rows)

        projected = self._project(clause, rows, is_with=False)
        cols: list[str] = []
        for expr in clause.expressions or []:
            if isinstance(expr, a.Star):
                if projected:
                    cols = list(projected[0].keys())
                break
            cols.append(_proj_name(expr))
        result_rows = [[r.get(c, NULL) for c in cols] for r in projected]
        return cols, result_rows

    def _aggregate_return(
        self, clause: a.Return, rows: list[Row]
    ) -> tuple[list[str], list[list[t.Any]]]:
        # Simple: no GROUP BY keys beyond non-agg expressions treated as keys
        keys = [e for e in (clause.expressions or []) if not _is_agg(e)]
        groups: dict[tuple[t.Any, ...], list[Row]] = {}
        for row in rows:
            env = self._env(row)
            key = tuple(_freeze(eval_expr(k, env)) for k in keys)
            groups.setdefault(key, []).append(row)

        cols = [_proj_name(e) for e in (clause.expressions or [])]
        result_rows: list[list[t.Any]] = []
        for key, group_rows in groups.items():
            out_row: list[t.Any] = []
            key_iter = iter(key)
            for expr in clause.expressions or []:
                if _is_agg(expr):
                    out_row.append(_eval_agg(expr, group_rows, self))
                else:
                    out_row.append(next(key_iter))
            result_rows.append(out_row)

        # ORDER BY / SKIP / LIMIT on aggregated result via temp projection
        if clause.order or clause.skip or clause.limit or clause.distinct:
            tmp_rows = [dict(zip(cols, r, strict=False)) for r in result_rows]
            # Build a fake Return without aggs for ordering
            fake = a.Return(
                expressions=[a.Identifier(this=c) for c in cols],
                order=clause.order,
                skip=clause.skip,
                limit=clause.limit,
                distinct=clause.distinct,
            )
            tmp_rows = self._project(fake, tmp_rows, is_with=False)
            result_rows = [[r[c] for c in cols] for r in tmp_rows]
        return cols, result_rows

    def _unwind(self, clause: a.Unwind, rows: list[Row]) -> list[Row]:
        out: list[Row] = []
        name = clause.alias.this if isinstance(clause.alias, a.Identifier) else "x"
        for row in rows:
            val = eval_expr(clause.expression, self._env(row))
            if is_null(val):
                continue
            if not isinstance(val, list):
                val = [val]
            for item in val:
                out.append({**row, name: item})
        return out

    def _create(self, clause: a.Create, rows: list[Row]) -> list[Row]:
        out: list[Row] = []
        for row in rows:
            out.append(self._create_pattern(clause.pattern, row))
        return out if out else [self._create_pattern(clause.pattern, {})]

    def _create_pattern(self, pattern: a.Pattern, row: Row) -> Row:
        r = dict(row)
        for path in pattern.paths:
            elems = path.elements
            i = 0
            prev_node: Node | None = None
            while i < len(elems):
                el = elems[i]
                if isinstance(el, a.NodePattern):
                    node = self._create_node(el, r)
                    if el.variable:
                        r[el.variable.this] = node
                    prev_node = node
                    i += 1
                elif isinstance(el, a.RelationshipPattern):
                    nxt = elems[i + 1]
                    assert isinstance(nxt, a.NodePattern)
                    end = self._create_node(nxt, r)
                    if nxt.variable:
                        r[nxt.variable.this] = end
                    assert prev_node is not None
                    rel = self._create_rel(el, prev_node, end, r)
                    if el.variable:
                        r[el.variable.this] = rel
                    prev_node = end
                    i += 2
                else:
                    i += 1
        return r

    def _create_node(self, pat: a.NodePattern, row: Row) -> Node:
        if pat.variable and pat.variable.this in row and isinstance(row[pat.variable.this], Node):
            return t.cast(Node, row[pat.variable.this])
        labels = pat.labels.labels if isinstance(pat.labels, a.LabelExpression) else []
        props: dict[str, t.Any] = {}
        if isinstance(pat.properties, a.Map):
            env = self._env(row)
            for k, v in pat.properties.entries:
                props[k] = eval_expr(v, env)
                if props[k] is NULL:
                    props[k] = None
        return self.graph.create_node(labels, **{k: v for k, v in props.items() if v is not None})

    def _create_rel(
        self, pat: a.RelationshipPattern, start: Node, end: Node, row: Row
    ) -> Relationship:
        typ = (pat.types or ["REL"])[0]
        props: dict[str, t.Any] = {}
        if isinstance(pat.properties, a.Map):
            env = self._env(row)
            for k, v in pat.properties.entries:
                props[k] = eval_expr(v, env)
        if pat.direction is a.Direction.INCOMING:
            start, end = end, start
        return self.graph.create_rel(start, end, typ, **{k: v for k, v in props.items() if v is not NULL})

    def _merge(self, clause: a.Merge, rows: list[Row]) -> list[Row]:
        out: list[Row] = []
        for row in rows:
            matched = self._match_pattern(clause.pattern, row)
            if matched:
                r = matched[0]
                for action in clause.actions or []:
                    if isinstance(action, a.OnMatch):
                        for s in action.actions:
                            if isinstance(s, a.Set):
                                r = self._set(s, [r])[0]
                out.append(r)
            else:
                r = self._create_pattern(clause.pattern, row)
                for action in clause.actions or []:
                    if isinstance(action, a.OnCreate):
                        for s in action.actions:
                            if isinstance(s, a.Set):
                                r = self._set(s, [r])[0]
                out.append(r)
        return out

    def _set(self, clause: a.Set, rows: list[Row]) -> list[Row]:
        for row in rows:
            env = self._env(row)
            for item in clause.items:
                assert isinstance(item, a.SetItem)
                val = eval_expr(item.expression, env)
                target = item.this
                if isinstance(target, a.Property):
                    obj = eval_expr(target.this, env)
                    if isinstance(obj, (Node, Relationship)):
                        if item.op == "+=":
                            if isinstance(val, dict):
                                obj.props.update(val)
                        else:
                            if val is NULL:
                                obj.props.pop(target.name, None)
                            else:
                                obj.props[target.name] = val
                elif isinstance(target, a.Identifier):
                    # SET n = map or SET n:Label — labels via LabelExpression not modeled on left
                    obj = row.get(target.this)
                    if isinstance(obj, Node) and isinstance(val, dict):
                        if item.op == "+=":
                            obj.props.update(val)
                        else:
                            obj.props = dict(val)
        return rows

    def _delete(self, clause: a.Delete, rows: list[Row]) -> list[Row]:
        for row in rows:
            env = self._env(row)
            for expr in clause.expressions:
                obj = eval_expr(expr, env)
                if isinstance(obj, Node):
                    self.graph.delete_node(obj.id, detach=bool(clause.detach))
                elif isinstance(obj, Relationship):
                    self.graph.delete_rel(obj.id)
        return rows

    def _remove(self, clause: a.Remove, rows: list[Row]) -> list[Row]:
        for row in rows:
            env = self._env(row)
            for item in clause.items:
                if isinstance(item, a.Property):
                    obj = eval_expr(item.this, env)
                    if isinstance(obj, (Node, Relationship)):
                        obj.props.pop(item.name, None)
                elif isinstance(item, a.NodePattern) and isinstance(item.variable, a.Identifier):
                    obj = row.get(item.variable.this)
                    if isinstance(obj, Node) and isinstance(item.labels, a.LabelExpression):
                        for lab in item.labels.labels or []:
                            obj.labels.discard(lab)
                            if lab in self.graph._by_label:
                                self.graph._by_label[lab].discard(obj.id)
        return rows

    def _foreach(self, clause: a.Foreach, rows: list[Row]) -> list[Row]:
        out: list[Row] = []
        for row in rows:
            env = self._env(row)
            seq = eval_expr(clause.expression, env)
            if is_null(seq):
                out.append(row)
                continue
            items = list(seq) if not isinstance(seq, (str, bytes)) else list(seq)
            var_name = (
                clause.variable.this
                if isinstance(clause.variable, a.Identifier)
                else "_foreach"
            )
            current = dict(row)
            for item in items:
                current[str(var_name)] = item
                for body in clause.clauses or []:
                    if isinstance(body, a.Create):
                        current = self._create(body, [current])[0]
                    elif isinstance(body, a.Merge):
                        current = self._merge(body, [current])[0]
                    elif isinstance(body, a.Set):
                        current = self._set(body, [current])[0]
                    elif isinstance(body, a.Delete):
                        current = self._delete(body, [current])[0]
                    elif isinstance(body, a.Remove):
                        current = self._remove(body, [current])[0]
                    elif isinstance(body, a.Foreach):
                        current = self._foreach(body, [current])[0]
                    else:
                        raise ExecuteError(
                            f"Unsupported FOREACH body {type(body).__name__}",
                            code="CG1702",
                        )
            out.append({k: v for k, v in current.items() if k != var_name or k in row})
        return out


def _pattern_vars(pattern: a.Pattern) -> list[str]:
    names: list[str] = []
    for n in pattern.walk():
        if isinstance(n, (a.NodePattern, a.RelationshipPattern, a.PathPattern)) and isinstance(
            n.variable, a.Identifier
        ):
            names.append(n.variable.this)
    return names


def _proj_name(expr: a.AstNode) -> str:
    if isinstance(expr, a.Alias) and isinstance(expr.alias, a.Identifier):
        return str(expr.alias.this)
    if isinstance(expr, a.Identifier):
        return str(expr.this)
    if isinstance(expr, a.Property):
        return str(expr.name)
    if isinstance(expr, a.FunctionCall):
        return str(expr.name).lower()
    return expr.cypher()


def _is_agg(expr: a.AstNode) -> bool:
    node = expr.this if isinstance(expr, a.Alias) else expr
    if isinstance(node, a.FunctionCall):
        return node.name.lower() in {"count", "sum", "avg", "min", "max", "collect"}
    return False


def _eval_agg(expr: a.AstNode, rows: list[Row], engine: Engine) -> t.Any:
    node = expr.this if isinstance(expr, a.Alias) else expr
    assert isinstance(node, a.FunctionCall)
    name = node.name.lower()
    if name == "count":
        if node.expressions and isinstance(node.expressions[0], a.Star):
            return len(rows)
        vals = [eval_expr(node.expressions[0], engine._env(r)) for r in rows]
        return sum(1 for v in vals if not is_null(v))
    vals = [eval_expr(node.expressions[0], engine._env(r)) for r in rows]
    vals = [v for v in vals if not is_null(v)]
    if name == "sum":
        return sum(vals) if vals else NULL
    if name == "avg":
        return (sum(vals) / len(vals)) if vals else NULL
    if name == "min":
        return min(vals) if vals else NULL
    if name == "max":
        return max(vals) if vals else NULL
    if name == "collect":
        return vals
    raise ExecuteError(f"Unknown agg {name}", code="CG1702")


def _freeze(v: t.Any) -> t.Any:
    if is_null(v):
        return ("null",)
    if isinstance(v, (Node, Relationship)):
        return ("ent", type(v).__name__, v.id)
    if isinstance(v, list):
        return ("list", tuple(_freeze(x) for x in v))
    if isinstance(v, dict):
        return ("map", tuple(sorted((k, _freeze(x)) for k, x in v.items())))
    return v


def _sort_val(v: t.Any) -> t.Any:
    if is_null(v):
        return ()
    if isinstance(v, (Node, Relationship)):
        return v.id
    return v
