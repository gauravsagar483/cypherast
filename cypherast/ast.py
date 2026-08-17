"""Unified AstNode IR meta-model and Cypher/GQL node catalog."""

from __future__ import annotations

import typing as t
from copy import deepcopy
from enum import Enum, auto


class Direction(Enum):
    OUTGOING = auto()  # -[:T]->
    INCOMING = auto()  # <-[:T]-
    BOTH = auto()  # -[:T]-


class AstNode:
    """Base IR node. All Cypher/GQL constructs are subclasses of this."""

    arg_types: dict[str, t.Any] = {}

    def __init__(self, **args: t.Any) -> None:
        self.args: dict[str, t.Any] = {}
        self.parent: AstNode | None = None
        self.type: t.Any = None  # filled by annotate_types
        for key, value in args.items():
            self.set(key, value)
        for key in self.arg_types:
            if key not in self.args:
                self.args[key] = None

    def set(self, key: str, value: t.Any) -> None:
        if isinstance(value, AstNode):
            value.parent = self
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, AstNode):
                    item.parent = self
        self.args[key] = value

    def __getattr__(self, key: str) -> t.Any:
        # Avoid recursion during half-constructed deepcopy / hasattr probes
        if key in ("args", "parent", "type", "arg_types") or key.startswith("_"):
            raise AttributeError(key)
        try:
            args = object.__getattribute__(self, "args")
        except AttributeError as e:
            raise AttributeError(key) from e
        try:
            return args[key]
        except KeyError as e:
            raise AttributeError(key) from e

    def __setattr__(self, key: str, value: t.Any) -> None:
        if key in ("args", "parent", "type", "arg_types") or key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self.set(key, value)

    def copy(self) -> AstNode:
        """Deep-copy the tree without following parent pointers (avoid cycles)."""

        def _clone_value(value: t.Any) -> t.Any:
            if isinstance(value, AstNode):
                return _clone(value)
            if isinstance(value, list):
                return [_clone_value(item) for item in value]
            if isinstance(value, tuple):
                return tuple(_clone_value(item) for item in value)
            if isinstance(value, dict):
                return {k: _clone_value(v) for k, v in value.items()}
            return deepcopy(value)

        def _clone(node: AstNode) -> AstNode:
            cls = type(node)
            kwargs = {key: _clone_value(value) for key, value in node.args.items()}
            cloned = cls(**kwargs)
            cloned.type = node.type
            return cloned

        return _clone(self)

    def walk(self) -> t.Iterator[AstNode]:
        yield self
        for value in self.args.values():
            if isinstance(value, AstNode):
                yield from value.walk()
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, AstNode):
                        yield from item.walk()

    def find(self, *types: type[AstNode]) -> AstNode | None:
        for node in self.walk():
            if isinstance(node, types):
                return node
        return None

    def find_all(self, *types: type[AstNode]) -> list[AstNode]:
        return [n for n in self.walk() if isinstance(n, types)]

    def transform(self, fun: t.Callable[[AstNode], AstNode | None], copy: bool = True) -> AstNode:
        root = self.copy() if copy else self

        def _apply(node: AstNode) -> AstNode:
            for key, value in list(node.args.items()):
                if isinstance(value, AstNode):
                    node.set(key, _apply(value))
                elif isinstance(value, list):
                    new_list = []
                    for item in value:
                        if isinstance(item, AstNode):
                            new_list.append(_apply(item))
                        else:
                            new_list.append(item)
                    node.set(key, new_list)
            result = fun(node)
            return node if result is None else result

        return _apply(root)

    def replace(self, old: AstNode, new: AstNode) -> None:
        if self.parent is None:
            return
        for key, value in self.parent.args.items():
            if value is old:
                self.parent.set(key, new)
                return
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if item is old:
                        value[i] = new
                        new.parent = self.parent
                        return

    def assert_is(self, typ: type[AstNode]) -> AstNode:
        if not isinstance(self, typ):
            raise TypeError(f"Expected {typ.__name__}, got {type(self).__name__}")
        return self

    def cypher(self, pretty: bool = False, dialect: str | None = None) -> str:
        """Render this AST node as Cypher text."""
        from cypherast.dialects import get_dialect
        from cypherast.renderer import Renderer

        d = get_dialect(dialect) if dialect else None
        renderer = d.renderer() if d else Renderer()
        return renderer.generate(self, pretty=pretty)

    def __repr__(self) -> str:
        parts = []
        for k, v in self.args.items():
            if v is None:
                continue
            parts.append(f"{k}={v!r}")
        return f"{type(self).__name__}({', '.join(parts)})"

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        assert isinstance(other, AstNode)
        return self.args == other.args


# ---------------------------------------------------------------------------
# Literals & atoms
# ---------------------------------------------------------------------------


class Literal(AstNode):
    arg_types = {"this": True}


class Null(Literal):
    def __init__(self, this: t.Any = None) -> None:
        super().__init__(this=None)


class Boolean(Literal):
    arg_types = {"this": True}


class Integer(Literal):
    arg_types = {"this": True}


class Float(Literal):
    arg_types = {"this": True}


class String(Literal):
    arg_types = {"this": True}


class Parameter(AstNode):
    arg_types = {"name": True}


class Identifier(AstNode):
    arg_types = {"this": True}


class Star(AstNode):
    """RETURN * or map projection .* ."""

    arg_types = {}


class PropertySelector(AstNode):
    """Map projection property selector: ``n{.name}`` (distinct from bare ``n{name}``)."""

    arg_types = {"name": True}


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


class Property(AstNode):
    arg_types = {"this": True, "name": True}


class LabelPredicate(AstNode):
    """``n:Label`` node label or relationship type predicate in expressions."""

    arg_types = {"this": True, "labels": True}


class Map(AstNode):
    arg_types = {"entries": True}  # list[(key, value)]


class List(AstNode):
    arg_types = {"expressions": True}


class ListSubscript(AstNode):
    """``expr[index]`` — Cypher list/string indexing (0-based in openCypher)."""

    arg_types = {"this": True, "index": True}


class ListSlice(AstNode):
    """``expr[start..end]`` or ``expr[start..]`` list slice."""

    arg_types = {"this": True, "start": False, "end": False}


class Range(AstNode):
    arg_types = {"start": False, "end": False}


class Alias(AstNode):
    arg_types = {"this": True, "alias": True}


class Binary(AstNode):
    arg_types = {"this": True, "expression": True}


class Add(Binary):
    pass


class Sub(Binary):
    pass


class Mul(Binary):
    pass


class Div(Binary):
    pass


class Mod(Binary):
    pass


class Pow(Binary):
    pass


class EQ(Binary):
    pass


class NEQ(Binary):
    pass


class LT(Binary):
    pass


class LTE(Binary):
    pass


class GT(Binary):
    pass


class GTE(Binary):
    pass


class And(Binary):
    pass


class Or(Binary):
    pass


class Xor(Binary):
    pass


class In(Binary):
    pass


class StartsWith(Binary):
    pass


class EndsWith(Binary):
    pass


class Contains(Binary):
    pass


class RegexMatch(Binary):
    """openCypher regular-expression predicate: ``value =~ pattern``."""


class Unary(AstNode):
    arg_types = {"this": True}


class Not(Unary):
    pass


class Neg(Unary):
    pass


class IsNull(AstNode):
    arg_types = {"this": True, "not_": False}


class FunctionCall(AstNode):
    arg_types = {"name": True, "expressions": True, "distinct": False}


class Case(AstNode):
    arg_types = {"this": False, "ifs": True, "default": False}  # ifs: list[(cond, then)]


class Coalesce(AstNode):
    arg_types = {"expressions": True}


class ListComprehension(AstNode):
    arg_types = {"variable": True, "source": True, "where": False, "projection": False}


class Quantifier(AstNode):
    """``all/any/none/single(x IN list WHERE pred)``."""

    arg_types = {"name": True, "variable": True, "source": True, "where": False}


class ListLambda(AstNode):
    """Legacy ``filter``/``extract`` and ``reduce`` list expressions."""

    arg_types = {
        "name": True,
        "variable": True,
        "source": True,
        "expression": True,
        "accumulator": False,
        "initial": False,
    }


class PatternComprehension(AstNode):
    arg_types = {"variable": False, "pattern": True, "where": False, "projection": True}


class MapProjection(AstNode):
    arg_types = {"this": True, "entries": True}


class PatternPredicate(AstNode):
    """``EXISTS`` / ``NOT`` pattern form in WHERE: ``(n)-->(m)`` as a predicate."""

    arg_types = {"pattern": True, "not_": False}


class CountSubquery(AstNode):
    """COUNT subquery expression: ``COUNT { pattern-or-query }``."""

    arg_types = {"query": True}


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------


class LabelExpression(AstNode):
    """Label set or Neo4j label expression (A&B|!C%)."""

    arg_types = {"labels": True, "expression": False}


class NodePattern(AstNode):
    arg_types = {
        "variable": False,
        "labels": False,
        "properties": False,
        "where": False,
    }


class RelationshipPattern(AstNode):
    arg_types = {
        "variable": False,
        "types": False,  # list[str]
        "properties": False,
        "direction": True,
        "min_hops": False,
        "max_hops": False,  # None = unbounded when * present
        "variable_length": False,
        "where": False,
        "memgraph_quantifier": False,
        "memgraph_weight_expr": False,
        "memgraph_total_weight": False,
    }


class PathPattern(AstNode):
    """Alternating node / relationship sequence. Optional path variable."""

    arg_types = {"variable": False, "elements": True}


class Pattern(AstNode):
    """Comma-separated path patterns in MATCH/CREATE/MERGE."""

    arg_types = {"paths": True}


class ShortestPath(AstNode):
    arg_types = {"this": True, "all_": False}


class RelationshipLambda(AstNode):
    """``(rel, node | expr)`` weight or filter lambda on a Memgraph quantifier."""

    arg_types = {"relationship": True, "node": True, "expression": True}


class QuantifiedPath(AstNode):
    """Neo4j quantified path pattern (parse-tolerant in v1)."""

    arg_types = {"this": True, "min_hops": False, "max_hops": False}


# ---------------------------------------------------------------------------
# Clauses
# ---------------------------------------------------------------------------


class Match(AstNode):
    arg_types = {"pattern": True, "optional": False, "where": False, "hints": False, "search": False}


class Where(AstNode):
    arg_types = {"this": True}


class With(AstNode):
    arg_types = {
        "expressions": True,
        "distinct": False,
        "where": False,
        "order": False,
        "skip": False,
        "limit": False,
        "group_by": False,
    }


class Return(AstNode):
    arg_types = {
        "expressions": True,
        "distinct": False,
        "order": False,
        "skip": False,
        "limit": False,
        "group_by": False,
    }


class For(AstNode):
    """``FOR x IN list RETURN …`` (Cypher 25; equivalent to UNWIND)."""

    arg_types = {"expression": True, "alias": True}


class GroupBy(AstNode):
    arg_types = {"expressions": True}


class Unwind(AstNode):
    arg_types = {"expression": True, "alias": True}


class Order(AstNode):
    arg_types = {"expressions": True}  # list[Ordered]


class Ordered(AstNode):
    arg_types = {"this": True, "desc": False, "nulls": False}  # "FIRST" | "LAST"


class Skip(AstNode):
    arg_types = {"this": True}


class Limit(AstNode):
    arg_types = {"this": True}


class Create(AstNode):
    arg_types = {"pattern": True}


class Merge(AstNode):
    arg_types = {"pattern": True, "actions": False}  # list[OnCreate|OnMatch]


class OnCreate(AstNode):
    arg_types = {"actions": True}


class OnMatch(AstNode):
    arg_types = {"actions": True}


class Set(AstNode):
    arg_types = {"items": True}


class SetItem(AstNode):
    arg_types = {"this": True, "expression": False, "op": False}  # = or +=


class Delete(AstNode):
    arg_types = {"expressions": True, "detach": False}


class Remove(AstNode):
    arg_types = {"items": True}


class RemoveLabels(AstNode):
    """``REMOVE n:Label(:Label2…)`` — not a NodePattern (avoids EXISTS render)."""

    arg_types = {"this": True, "labels": True}  # Identifier + LabelExpression


class Foreach(AstNode):
    arg_types = {"variable": True, "expression": True, "clauses": True}


class CallSubquery(AstNode):
    """``CALL (vars) { … } [IN TRANSACTIONS …]`` subquery."""

    arg_types = {
        "query": True,
        "variables": False,
        "optional": False,
        "in_transactions": False,
        "transaction_rows": False,
    }


class FilterItem(AstNode):
    arg_types = {"variable": True, "predicate": True}


class Filter(AstNode):
    arg_types = {"items": True}  # list[FilterItem]


class Let(AstNode):
    arg_types = {"items": True}  # list[Alias]


class LoadCsv(AstNode):
    arg_types = {
        "url": True,
        "alias": True,
        "with_headers": False,
        "fieldterminator": False,
    }


class Search(AstNode):
    """``SEARCH var IN (VECTOR INDEX …)`` on MATCH (neo4j25)."""

    arg_types = {
        "variable": True,
        "index_name": True,
        "vector_expr": True,
        "limit": False,
        "score_alias": False,
    }


class WhenBranch(AstNode):
    """One ``WHEN cond THEN { query }`` arm of a composed query."""

    arg_types = {"condition": True, "query": True}


class WhenQuery(AstNode):
    """``WHEN cond THEN { query } … [ELSE { query }]`` composed query.

    Branches are ``WhenBranch`` nodes rather than tuples so ``walk`` / ``find`` /
    ``transform`` reach the conditions and branch bodies.
    """

    arg_types = {"branches": True, "default": False}


class AdminStatement(AstNode):
    """CREATE INDEX / CONSTRAINT / SHOW … (admin lane)."""

    arg_types = {"text": True}


class CallProcedure(AstNode):
    """``CALL ns.proc(args) [YIELD …] [WHERE …]`` (openCypher / Neo4j / PuppyGraph / Memgraph)."""

    arg_types = {
        "name": True,  # dotted procedure name string, e.g. ``algo.wcc``
        "expressions": True,  # argument list
        "yield_": False,  # Yield node or None
        "where": False,  # optional Where after YIELD
    }


class Union(AstNode):
    arg_types = {"this": True, "expression": True, "distinct": False}


class Query(AstNode):
    """Single query: sequence of clauses ending in RETURN/FINISH or updates."""

    arg_types = {"clauses": True}


class Cypher(AstNode):
    """Top-level statement (may be a Query or Union)."""

    arg_types = {"this": True, "version": False}


# ---------------------------------------------------------------------------
# GQL-only nodes (IR-forward; Cypher dialects raise CompatibilityError on emit)
# ---------------------------------------------------------------------------


class Next(AstNode):
    arg_types = {"this": True, "expression": True}


class Insert(AstNode):
    arg_types = {"pattern": True}


class CreateGraphType(AstNode):
    arg_types = {"name": True, "body": False}


class GraphTypeRef(AstNode):
    arg_types = {"name": True}


class SessionCommand(AstNode):
    arg_types = {"command": True}


class TransactionCommand(AstNode):
    arg_types = {"command": True}


class BindingTable(AstNode):
    arg_types = {"columns": True}


class ValueTable(AstNode):
    arg_types = {"columns": True}


class Use(AstNode):
    arg_types = {"graph": True}


class Yield(AstNode):
    """``YIELD`` field list on a procedure ``CALL`` (also used for ``YIELD *``)."""

    arg_types = {"expressions": True}


class Placeholder(AstNode):
    """Lineage leaf when a binding source is unknown."""

    arg_types = {"name": False}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def convert(value: t.Any) -> AstNode:
    """Wrap a Python value as a literal AstNode."""
    if isinstance(value, AstNode):
        return value
    if value is None:
        return Null()
    if isinstance(value, bool):
        return Boolean(this=value)
    if isinstance(value, int):
        return Integer(this=value)
    if isinstance(value, float):
        return Float(this=value)
    if isinstance(value, str):
        return String(this=value)
    if isinstance(value, list):
        return List(expressions=[convert(v) for v in value])
    if isinstance(value, dict):
        return Map(entries=[(k, convert(v)) for k, v in value.items()])
    raise TypeError(f"Cannot convert {type(value)} to AstNode")
