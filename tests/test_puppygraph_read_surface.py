"""Golden read-surface tests derived from a live PuppyGraph probe."""

from __future__ import annotations

import pytest

import cypherast
from cypherast.errors import ValidationError


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n) RETURN count(*) AS x",
        "RETURN date('2026-08-10') AS x",
        "RETURN datetime() AS x",
        "RETURN duration({days: 3}) AS x",
        "RETURN duration.between(date('2026-01-01'), date('2026-08-10')) AS x",
        "RETURN toStringOrNull(1) AS x",
        "RETURN toIntegerOrNull('x') AS x",
        "RETURN toFloatOrNull('x') AS x",
        "RETURN toBooleanOrNull('x') AS x",
        "RETURN isEmpty('') AS x",
        "RETURN char_length('abc') AS x",
        "RETURN character_length('abc') AS x",
        "RETURN randomUUID() AS x",
        "RETURN valueType(1) AS x",
        "RETURN nullIf(1, 1) AS x",
        "RETURN toStringList([1, 2]) AS x",
        "RETURN haversin(1) AS x",
        "RETURN range(1, 10, 2) AS x",
        "RETURN all(v IN [1, 2] WHERE v > 0) AS x",
        "RETURN any(v IN [1, 2] WHERE v > 1) AS x",
        "RETURN none(v IN [1, 2] WHERE v > 5) AS x",
        "RETURN [v IN [1, 2] WHERE v > 1 | v * 2] AS x",
        "RETURN [1] + [2] AS x",
        "RETURN 'abc' =~ 'a.*' AS x",
        "MATCH (a)--(b) RETURN count(*) AS x",
        "CALL { RETURN 1 AS t } RETURN t",
        "MATCH (n) WHERE exists(n.name) RETURN count(*) AS x",
        "MATCH (n) WHERE elementId(n) CONTAINS 'x' RETURN count(*) AS x",
        "MATCH ()-[r*1..2]->() RETURN count(r) AS x",
    ],
)
def test_verified_read_constructs_are_accepted(query: str) -> None:
    issues = cypherast.validate(query, dialect="puppygraph")
    assert not issues
    tree = cypherast.optimize(query, write="puppygraph")
    assert tree.cypher(dialect="puppygraph")


@pytest.mark.parametrize(
    "query",
    [
        "RETURN single(v IN [1, 2] WHERE v > 1) AS x",
        "RETURN keys({a: 1}) AS x",
        "MATCH ()-[r]->() RETURN startNode(r) AS x LIMIT 1",
        "MATCH ()-[r]->() RETURN endNode(r) AS x LIMIT 1",
        "RETURN isNaN(1.0) AS x",
        "RETURN normalize('abc') AS x",
        "RETURN localdatetime() AS x",
        "RETURN time() AS x",
        "RETURN localtime() AS x",
        "RETURN duration.inDays(date('2026-01-01'), date('2026-08-10')) AS x",
        "RETURN date.truncate('month', date('2026-08-10')) AS x",
        "RETURN point({x: 1.0, y: 2.0}) AS x",
        "MATCH (n) RETURN [(n)-->(m) | m] AS x LIMIT 1",
        "MATCH (n) RETURN n {.name} AS x LIMIT 1",
        "MATCH (n) WHERE EXISTS { (n)-->() } RETURN count(*) AS x",
        "MATCH (n) RETURN count { (n)-->() } AS x LIMIT 1",
        "RETURN reduce(s = 0, v IN [1, 2] | s + v) AS x",
        "RETURN extract(v IN [1, 2] | v * 2) AS x",
        "RETURN filter(v IN [1, 2] WHERE v > 1) AS x",
        "MATCH (n:A:B) RETURN count(*) AS x",
        "MATCH ()-[*]->() RETURN count(*) AS x",
        "MATCH (n) WHERE id(n) CONTAINS 'x' RETURN count(*) AS x",
        "CREATE (n:Probe) RETURN n",
        "MATCH (n) SET n.x = 1 RETURN n",
    ],
)
def test_verified_unsupported_constructs_are_rejected(query: str) -> None:
    issues = cypherast.validate(query, dialect="puppygraph")
    assert issues
    with pytest.raises(ValidationError):
        cypherast.optimize(query, write="puppygraph")


@pytest.mark.parametrize(
    "query",
    [
        # collect()-derived list carried through WITH, then concatenated (ET-06)
        "MATCH (m:Metric)-[:DERIVED_FROM]->(b:Metric) "
        "WITH m, collect(b.name) AS bases "
        "RETURN m.name AS metric, bases + ['x'] AS combined",
        "MATCH (m:Metric) "
        "WITH collect(m.name) AS a, collect(m.name) AS c "
        "RETURN a + c AS x",
        # collect() aggregate concatenated inline (engine reports mixing / ET-06)
        "MATCH (m:Metric) WITH collect(DISTINCT m.name) + [m.name] AS names RETURN names",
        # comprehension over a collect()-derived binding (ET-09)
        "MATCH (m:Metric) WITH collect(m) AS ms RETURN [x IN ms | x.name] AS names",
    ],
)
def test_aggregate_derived_list_ops_are_rejected(query: str) -> None:
    issues = cypherast.validate(query, dialect="puppygraph")
    assert issues
    assert any(
        "concat" in i.message.lower() or "list comprehension" in i.message.lower()
        for i in issues
    )


@pytest.mark.parametrize(
    "query",
    [
        # inline list literals — engine accepts
        "RETURN [1] + [2] AS x",
        "MATCH (m:Metric) RETURN [m.name] + ['z'] AS x",
        # comprehension over an inline list / non-aggregate binding — engine accepts
        "RETURN [v IN [1, 2] WHERE v > 1 | v * 2] AS x",
        "MATCH (m:Metric) RETURN [v IN [m.name] WHERE v <> '' | v] AS x",
        "MATCH (m:Metric) WITH m, range(1, 3) AS r RETURN [v IN r | v * 2] AS x",
    ],
)
def test_inline_and_non_aggregate_list_ops_are_accepted(query: str) -> None:
    assert not cypherast.validate(query, dialect="puppygraph")


def test_puppygraph_coalesce_requires_exactly_two_arguments() -> None:
    assert not cypherast.validate("RETURN coalesce(null, 1)", dialect="puppygraph")
    for query in ("RETURN coalesce(1)", "RETURN coalesce(null, null, 1)"):
        assert cypherast.validate(query, dialect="puppygraph")


def test_unlabelled_match_is_not_rewritten_to_synthetic_label() -> None:
    out = cypherast.optimize("MATCH (n) RETURN n", write="puppygraph").cypher(
        dialect="puppygraph"
    )
    assert "(n)" in out
    assert "_Node" not in out


def test_opencypher_remains_strict_for_puppygraph_extensions() -> None:
    assert cypherast.validate("RETURN exists(1)", dialect="opencypher")
    assert cypherast.validate("MATCH (a)--(b) RETURN a", dialect="opencypher")
    assert cypherast.validate("CALL { RETURN 1 AS t } RETURN t", dialect="opencypher")
