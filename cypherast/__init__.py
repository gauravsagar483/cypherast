"""cypherast — Cypher/GQL transpiler, rewriter, planner, executor."""

from __future__ import annotations

from cypherast import ast
from cypherast.dialects import dialect_names, get_dialect
from cypherast.errors import (
    CompatibilityError,
    CypherastError,
    ExecuteError,
    OptimizeError,
    ParseError,
    PlanError,
    SchemaError,
    TokenizeError,
    ValidationError,
)
from cypherast.lexer import Lexer, Token, TokenKind
from cypherast.lineage import lineage as _lineage_impl
from cypherast.parser import Parser


def parse(cypher: str, read: str | None = None) -> list[ast.AstNode]:
    """Parse one or more Cypher statements. Returns list of top-level AstNodes."""
    dialect = get_dialect(read)
    tree = dialect.parser(cypher).parse()
    return [tree]


def parse_one(cypher: str, read: str | None = None) -> ast.AstNode:
    """Parse a single Cypher statement into an AstNode (usually ``Cypher``)."""
    dialect = get_dialect(read)
    return dialect.parser(cypher).parse()


def optimize(
    cypher: str | ast.AstNode,
    schema: object | None = None,
    read: str | None = None,
    write: str | None = None,
    *,
    strict: bool = True,
    only: list[str] | tuple[str, ...] | None = None,
    disable: list[str] | tuple[str, ...] | None = None,
    constraint_only: list[str] | tuple[str, ...] | None = None,
    constraint_disable: list[str] | tuple[str, ...] | None = None,
) -> ast.AstNode:
    """Canonicalize + apply target-dialect capability constraints.

    ``read`` selects the parser dialect; ``write`` (default ``read``) selects
    capability rewrites (e.g. puppygraph LIMIT / no Cartesian MATCH).

    Rules are named. Filter with ``only`` / ``disable`` for canonicalizer rules,
    and ``constraint_only`` / ``constraint_disable`` for dialect constraints
    (e.g. ``strip_nulls_order_modifiers``, ``guard_optional_scalar_use``).

    After rewrite, remaining dialect/schema violations raise ``ValidationError``
    (same codes as ``validate``: CG12xx–CG14xx). Pass ``strict=False`` only to
    get a rewritten AST that may still be invalid for the target engine.

    Pass ``schema=GraphSchema(...)`` for labelling + catalog checks
    (id-fields; when ``schema.strict``, unknown labels/rels + undeclared props).
    """
    from cypherast.dialects.dialect import get_dialect_cls

    tree = cypher if isinstance(cypher, ast.AstNode) else parse_one(cypher, read=read)
    target = get_dialect_cls(write or read)
    return target.optimize(
        tree,
        schema=schema,
        strict=strict,
        only=only,
        disable=disable,
        constraint_only=constraint_only,
        constraint_disable=constraint_disable,
    )


def translate(
    cypher: str,
    *,
    from_: str | None = None,
    to_: str | None = None,
    pretty: bool = False,
    optimize: bool = False,
    strict: bool | None = None,
    only: list[str] | tuple[str, ...] | None = None,
    disable: list[str] | tuple[str, ...] | None = None,
    constraint_only: list[str] | tuple[str, ...] | None = None,
    constraint_disable: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Parse with ``from_`` dialect and render with ``to_`` dialect (transpile).

    When ``optimize=True``, runs shared rewriter + target capability constraints
    before render, then raises ``ValidationError`` on remaining dialect issues
    (same as ``optimize``). Override with ``strict=False`` for soft emit.
    Plain transpile (``optimize=False``) does not validate unless ``strict=True``.
    """
    from cypherast.dialects.constraints import raise_if_invalid
    from cypherast.dialects.dialect import get_dialect_cls

    if strict is None:
        strict = optimize

    tree = parse_one(cypher, read=from_)
    target_cls = get_dialect_cls(to_ or from_)
    if optimize:
        tree = target_cls.optimize(
            tree,
            strict=strict,
            only=only,
            disable=disable,
            constraint_only=constraint_only,
            constraint_disable=constraint_disable,
        )
    else:
        tree = target_cls.apply_constraints(
            tree, only=constraint_only, disable=constraint_disable
        )
        if strict:
            raise_if_invalid(tree, target_cls.capabilities)
    return target_cls.renderer().generate(tree, pretty=pretty)


# Alias for translate
transpile = translate


def validate(
    cypher: str | ast.AstNode,
    *,
    read: str | None = None,
    dialect: str | None = None,
    schema: object | None = None,
) -> list[object]:
    """Return capability ``ConstraintIssue`` list for ``dialect`` (default ``read``).

    ``optimize(..., write=dialect)`` already raises on these issues by default.
    Use ``validate`` to inspect without rewriting, or after ``optimize(..., strict=False)``.

    Pass ``schema=GraphSchema(...)`` to reject id-field property access and,
    when ``schema.strict``, unknown labels/rel types and undeclared properties.
    """
    from cypherast.dialects.dialect import get_dialect_cls

    tree = cypher if isinstance(cypher, ast.AstNode) else parse_one(cypher, read=read)
    return list(get_dialect_cls(dialect or read).validate(tree, schema=schema))



def explain(cypher: str, schema: object | None = None, read: str | None = None) -> str:
    """Return textual EXPLAIN plan."""
    from cypherast.planner import explain as _explain

    tree = parse_one(cypher, read=read)
    return _explain(tree, schema=schema)


def profile(
    cypher: str,
    *,
    schema: object | None = None,
    graph: object | None = None,
    read: str | None = None,
) -> str:
    """Run with profiling and return plan + row counts."""
    from cypherast.planner import profile as _profile

    tree = parse_one(cypher, read=read)
    return _profile(tree, schema=schema, graph=graph)


def run(
    cypher: str,
    *,
    graph: object | None = None,
    schema: object | None = None,
    read: str | None = None,
) -> object:
    """Execute Cypher against an in-memory Graph."""
    from cypherast.executor import execute
    from cypherast.executor.graph import Graph

    tree = parse_one(cypher, read=read)
    g = graph if isinstance(graph, Graph) or graph is None else None
    if graph is not None and not isinstance(graph, Graph):
        raise TypeError("graph must be a cypherast.executor.Graph")
    return execute(tree, graph=g, schema=schema)


def lineage(
    cypher: str | ast.AstNode,
    binding: str | None = None,
    *,
    schema: object | None = None,
    from_: str | None = None,
) -> object:
    """Binding-level provenance graph for a Cypher query."""
    # Must not lazy-import ``cypherast.lineage`` inside this function: that
    # rebinds the package attribute to the submodule and breaks later calls.
    tree = cypher if isinstance(cypher, ast.AstNode) else parse_one(cypher, read=from_)
    return _lineage_impl(tree, binding=binding, schema=schema)


__all__ = [
    "CompatibilityError",
    "CypherastError",
    "ExecuteError",
    "Lexer",
    "OptimizeError",
    "ParseError",
    "Parser",
    "PlanError",
    "SchemaError",
    "Token",
    "TokenKind",
    "TokenizeError",
    "ValidationError",
    "ast",
    "dialect_names",
    "explain",
    "get_dialect",
    "lineage",
    "optimize",
    "parse",
    "parse_one",
    "profile",
    "run",
    "transpile",
    "translate",
    "validate",
]
