"""Multidialect regression: every registered dialect + public API with explicit read/write.

Guards against accidentally testing only the default ``opencypher`` parser path.
"""

from __future__ import annotations

import pytest

import cypherast
from cypherast.dialects.dialect import get_dialect, get_dialect_cls
from cypherast.executor.graph import Graph

# Canonical engine names (opencypher9 is a first-class alias, not a web fixture dialect).
ALL_DIALECTS: tuple[str, ...] = (
    "opencypher",
    "opencypher9",
    "neo4j",
    "memgraph",
    "puppygraph",
)

# Labelled baseline — safe for optimize/validate on PuppyGraph too.
LABELLED = "MATCH (n:Person) WHERE n.status = 'A' RETURN n.name AS name"

# Parse-only surface (no dialect-specific capability rejects at parse time).
BASELINE_PARSE: tuple[str, ...] = (
    "RETURN 1 AS x",
    "MATCH (n:Person) RETURN n.name",
    "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name",
    "UNWIND [1, 2, 3] AS x RETURN x",
    "MATCH (n:Person) RETURN count(n)",
)


@pytest.fixture(params=ALL_DIALECTS, ids=list(ALL_DIALECTS))
def dialect(request: pytest.FixtureRequest) -> str:
    return request.param


def test_dialect_registry_includes_all_engines() -> None:
    names = set(cypherast.dialect_names())
    for name in ALL_DIALECTS:
        assert name in names, f"{name!r} missing from dialect_names()"


def test_default_read_is_opencypher() -> None:
    assert get_dialect(None).name == "opencypher"
    assert get_dialect_cls(None).name == "opencypher"


def test_opencypher9_alias_equivalence() -> None:
    q = "MATCH (n:Person) RETURN n.name"
    oc = cypherast.parse_one(q, read="opencypher")
    oc9 = cypherast.parse_one(q, read="opencypher9")
    assert oc.cypher() == oc9.cypher()
    assert get_dialect_cls("opencypher9") is not get_dialect_cls("opencypher")
    assert get_dialect_cls("opencypher9").__bases__[0] is get_dialect_cls("opencypher")


@pytest.mark.parametrize("query", BASELINE_PARSE, ids=[q[:40] for q in BASELINE_PARSE])
def test_parse_one_explicit_read(dialect: str, query: str) -> None:
    tree = cypherast.parse_one(query, read=dialect)
    assert tree is not None
    rendered = tree.cypher()
    assert isinstance(rendered, str) and rendered.strip()


@pytest.mark.parametrize("query", BASELINE_PARSE, ids=[q[:40] for q in BASELINE_PARSE])
def test_parse_list_explicit_read(dialect: str, query: str) -> None:
    trees = cypherast.parse(query, read=dialect)
    assert len(trees) == 1
    assert trees[0] is not None


def test_parse_roundtrip_per_dialect(dialect: str) -> None:
    tree = cypherast.parse_one(LABELLED, read=dialect)
    out = tree.cypher()
    tree2 = cypherast.parse_one(out, read=dialect)
    assert tree2.cypher() == out


def test_validate_returns_list(dialect: str) -> None:
    issues = cypherast.validate(LABELLED, read=dialect, dialect=dialect)
    assert isinstance(issues, list)


def test_optimize_soft_roundtrip(dialect: str) -> None:
    """strict=False: rewriter + constraints without raising residual issues."""
    opt = cypherast.optimize(LABELLED, read=dialect, write=dialect, strict=False)
    assert opt.cypher(dialect=dialect).strip()


@pytest.mark.parametrize(
    "from_,to_",
    [(a, b) for a in ALL_DIALECTS for b in ALL_DIALECTS],
    ids=[f"{a}->{b}" for a in ALL_DIALECTS for b in ALL_DIALECTS],
)
def test_translate_baseline_identity(from_: str, to_: str) -> None:
    out = cypherast.translate(LABELLED, from_=from_, to_=to_, optimize=False)
    assert "MATCH" in out.upper()
    cypherast.parse_one(out, read=to_)


def test_transpile_alias() -> None:
    q = LABELLED
    assert cypherast.transpile(q, from_="opencypher", to_="neo4j", optimize=False) == cypherast.translate(
        q, from_="opencypher", to_="neo4j", optimize=False
    )


def test_run_explicit_read(dialect: str) -> None:
    g = Graph()
    rows = list(
        cypherast.run(
            "CREATE (n:Person {name: 'Ada'}) RETURN n.name AS name",
            graph=g,
            read=dialect,
        )
    )
    assert rows == [{"name": "Ada"}]


def test_explain_explicit_read(dialect: str) -> None:
    plan = cypherast.explain(LABELLED, read=dialect)
    assert isinstance(plan, str) and plan.strip()


def test_profile_explicit_read(dialect: str) -> None:
    g = Graph()
    out = cypherast.profile(LABELLED, graph=g, read=dialect)
    assert isinstance(out, str) and out.strip()


def test_lineage_explicit_from(dialect: str) -> None:
    lg = cypherast.lineage(LABELLED, binding="name", from_=dialect)
    assert lg is not None


def test_parser_receives_dialect_name(dialect: str) -> None:
    cls = get_dialect_cls(dialect)
    parser = cls.parser("RETURN 1")
    assert parser.dialect == cls.name
