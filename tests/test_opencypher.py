"""openCypher 9 validation, render, functions, and executor coverage."""

from __future__ import annotations

import pytest

import cypherast
from cypherast import ast as a
from cypherast.errors import ValidationError
from cypherast.executor import Graph
from cypherast.schema import FUNCTION_SIGNATURES, lookup_function

_REJECT = [
    ("MATCH (n) FOREACH (x IN [1] | SET n.x = 1) RETURN n", "CG1501"),
    ("MERGE (n) ON CREATE SET n.x = 1 RETURN n", "CG1502"),
    ("MATCH (n)--(m) RETURN n", "CG1503"),
    ("MATCH ()-[r*1..2]->() RETURN r", "CG1504"),
    ("RETURN exists(1)", "CG1507"),
    ("CALL { MATCH (n) RETURN n } RETURN 1", "CG1505"),
    ("MATCH ((a)-[:R]->(b)){1,2} RETURN a", "CG1510"),
    ("RETURN unknownFn(1)", "CG1508"),
]

_ACCEPT = [
    "MATCH (n:Person) WHERE (n)-[:KNOWS]->() RETURN n",
    "CALL db.labels() YIELD label RETURN label",
    "RETURN [x IN range(1,3) | x]",
    "MATCH (n:Person) RETURN n.name",
]

_SCALAR_SMOKE: dict[str, str] = {
    "abs": "RETURN abs(-1)",
    "ceil": "RETURN ceil(1.2)",
    "floor": "RETURN floor(1.8)",
    "round": "RETURN round(1.5)",
    "sqrt": "RETURN sqrt(4)",
    "sign": "RETURN sign(-3)",
    "exp": "RETURN exp(1)",
    "log": "RETURN log(2.7)",
    "log10": "RETURN log10(100)",
    "e": "RETURN e()",
    "pi": "RETURN pi()",
    "rand": "RETURN rand()",
    "timestamp": "RETURN timestamp()",
    "sin": "RETURN sin(0)",
    "cos": "RETURN cos(0)",
    "tan": "RETURN tan(0)",
    "left": "RETURN left('abc', 2)",
    "right": "RETURN right('abc', 2)",
    "lTrim": "RETURN lTrim('  x')",
    "rTrim": "RETURN rTrim('x  ')",
    "length": "RETURN length('abc')",
    "range": "RETURN range(1, 3)",
    "coalesce": "RETURN coalesce(null, 1)",
    "toString": "RETURN toString(1)",
    "toInteger": "RETURN toInteger('2')",
    "toFloat": "RETURN toFloat('2.5')",
    "toBoolean": "RETURN toBoolean('true')",
    "head": "RETURN head([1,2])",
    "last": "RETURN last([1,2])",
    "tail": "RETURN tail([1,2])",
    "reverse": "RETURN reverse([1,2])",
    "split": "RETURN split('a,b', ',')",
    "substring": "RETURN substring('abc', 1, 2)",
    "replace": "RETURN replace('aba', 'a', 'x')",
    "trim": "RETURN trim('  x  ')",
    "toLower": "RETURN toLower('Ab')",
    "toUpper": "RETURN toUpper('Ab')",
}


def _graph() -> Graph:
    g = Graph()
    a_node = g.create_node(["Person"], name="Ada")
    b_node = g.create_node(["Person"], name="Alan")
    c_node = g.create_node(["Person"], name="Grace")
    g.create_rel(a_node, b_node, "KNOWS")
    g.create_rel(a_node, c_node, "KNOWS")
    return g


@pytest.mark.parametrize("query,code", _REJECT)
def test_oc9_rejects(query: str, code: str) -> None:
    issues = cypherast.validate(query, dialect="opencypher")
    assert any(i.code == code for i in issues), issues
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(query, write="opencypher")
    assert ei.value.code == code


@pytest.mark.parametrize("query", _ACCEPT)
def test_oc9_accepts(query: str) -> None:
    issues = cypherast.validate(query, dialect="opencypher")
    assert not issues
    tree = cypherast.optimize(query, write="opencypher")
    assert tree is not None


def test_opencypher9_alias_matches_opencypher() -> None:
    q = "RETURN exists(1)"
    oc = cypherast.validate(q, dialect="opencypher")
    oc9 = cypherast.validate(q, dialect="opencypher9")
    assert [i.code for i in oc] == [i.code for i in oc9]


def test_oc9_undefined_variable() -> None:
    issues = cypherast.validate("RETURN missing", dialect="opencypher")
    assert any(i.code == "CG1201" for i in issues)


def test_comparability_rejects_mixed_order() -> None:
    issues = cypherast.validate("RETURN true < 1", dialect="opencypher")
    assert any(i.code == "CG1512" for i in issues)


def test_comparability_rejects_mixed_equality() -> None:
    issues = cypherast.validate("RETURN 1 = 'x'", dialect="opencypher")
    assert any(i.code == "CG1512" for i in issues)


def test_using_hints_rejected() -> None:
    issues = cypherast.validate(
        "MATCH (n:Person) USING INDEX n:Person(name) RETURN n",
        dialect="opencypher",
    )
    assert any(i.code == "CG1511" for i in issues)


@pytest.mark.parametrize("name", sorted(FUNCTION_SIGNATURES))
def test_function_in_catalog(name: str) -> None:
    assert lookup_function(name) is not None


@pytest.mark.parametrize("name,query", list(_SCALAR_SMOKE.items()))
def test_scalar_function_parses(name: str, query: str) -> None:
    tree = cypherast.parse_one(query)
    assert tree is not None


@pytest.mark.parametrize("name,query", list(_SCALAR_SMOKE.items()))
def test_scalar_function_validates_oc9(name: str, query: str) -> None:
    issues = cypherast.validate(query, dialect="opencypher")
    assert not any(i.code in ("CG1508", "CG1509") for i in issues), issues


def test_pattern_predicate_no_exists_wrapper() -> None:
    q = "MATCH (n:Person) WHERE (n)-[:KNOWS]->() RETURN n"
    out = cypherast.parse_one(q).cypher(dialect="opencypher")
    assert "EXISTS" not in out.upper()
    assert "(n)-[:KNOWS]->()" in out.replace(" ", "") or "KNOWS" in out
    again = cypherast.parse_one(out)
    assert again.find(a.PatternPredicate) is not None


def test_not_pattern_predicate_roundtrip() -> None:
    q = "MATCH (n) WHERE NOT (n)-[:R]->() RETURN n"
    out = cypherast.parse_one(q).cypher(dialect="opencypher")
    assert "NOT" in out.upper()
    assert "EXISTS" not in out.upper()


def test_quantified_path_renders_opencypher() -> None:
    q = "MATCH ((a)-[:R]->(b)){1,2} RETURN a"
    out = cypherast.parse_one(q).cypher(dialect="opencypher")
    assert "{1,2}" in out.replace(" ", "")


def test_list_comprehension_roundtrip() -> None:
    q = "RETURN [x IN range(1, 3) | x]"
    out = cypherast.parse_one(q).cypher(dialect="opencypher")
    assert "range" in out
    assert cypherast.parse_one(out).find(a.ListComprehension) is not None


def test_regex_match_roundtrip() -> None:
    q = "RETURN 'abc' =~ 'a.*' AS ok"
    tree = cypherast.parse_one(q, read="opencypher")
    assert tree.find(a.RegexMatch) is not None
    assert "=~" in tree.cypher(dialect="opencypher")


def test_backticked_identifier_roundtrip() -> None:
    q = "RETURN 1 AS `weird name`"
    out = cypherast.parse_one(q, read="opencypher").cypher(dialect="opencypher")
    assert "`weird name`" in out
    assert cypherast.parse_one(out, read="opencypher") is not None


def test_list_comprehension_executor() -> None:
    result = cypherast.run("RETURN [x IN range(1, 3) | x * 2] AS xs", graph=Graph())
    assert list(result)[0]["xs"] == [2, 4, 6]


def test_list_comprehension_where_executor() -> None:
    result = cypherast.run("RETURN [x IN range(1, 5) WHERE x % 2 = 0 | x] AS evens", graph=Graph())
    assert list(result)[0]["evens"] == [2, 4]


def test_length_on_string() -> None:
    result = cypherast.run("RETURN length('abc') AS n", graph=Graph())
    assert list(result)[0]["n"] == 3


def test_path_functions() -> None:
    g = _graph()
    result = cypherast.run(
        "MATCH p=(a:Person)-[:KNOWS]->(b:Person) RETURN length(p) AS len, "
        "size(nodes(p)) AS nc, startNode(p).name AS s, endNode(p).name AS e",
        graph=g,
    )
    row = list(result)[0]
    assert row["len"] == 1
    assert row["nc"] == 2
    assert row["s"] == "Ada"
    assert row["e"] == "Alan"


def test_map_projection() -> None:
    g = Graph()
    g.create_node(["Person"], name="Ada", age=36)
    result = cypherast.run(
        "MATCH (n:Person) RETURN n {.name, age: n.age} AS m",
        graph=g,
    )
    row = list(result)[0]
    assert row["m"] == {"name": "Ada", "age": 36}


def test_call_procedure_db_labels() -> None:
    g = Graph()
    g.create_node(["Person"])
    g.create_node(["Company"])
    result = cypherast.run("CALL db.labels() YIELD label RETURN label", graph=g)
    labels = sorted(row["label"] for row in result)
    assert labels == ["Company", "Person"]


def test_shortest_path() -> None:
    g = _graph()
    result = cypherast.run(
        "MATCH shortestPath((a:Person {name: 'Ada'})-[:KNOWS*1..3]->(b:Person)) "
        "RETURN b.name AS name",
        graph=g,
    )
    names = sorted(row["name"] for row in result)
    assert names == ["Alan", "Grace"]


def test_stdev_aggregate() -> None:
    g = Graph()
    cypherast.run("CREATE (n:Person {v: 2}), (m:Person {v: 4})", graph=g)
    result = cypherast.run("MATCH (n:Person) RETURN stdev(n.v) AS s", graph=g)
    s = list(result)[0]["s"]
    assert round(s, 2) == 1.41


def test_cypher_version_header() -> None:
    tree = cypherast.parse_one("CYPHER 9 MATCH (n) RETURN n")
    assert tree.version == 9
    out = tree.cypher(dialect="opencypher")
    assert out.startswith("CYPHER 9")


def test_annotate_types_binds_node() -> None:
    tree = cypherast.optimize("MATCH (n:Person) RETURN n.name", write="opencypher")
    for n in tree.walk():
        if isinstance(n, a.Identifier) and n.this == "n":
            assert n.type == "node"
            break
    else:
        raise AssertionError("n not typed as node")


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (a)-[:R]->(b) WHERE a:A RETURN a",
        "MATCH (n) DELETE n:Person",
        "MATCH (n) SET n :Foo RETURN labels(n)",
        "MATCH (x:Begin) CREATE (x)-[:TYPE]->(:End)",
        "WITH [1, 2, 3] AS list RETURN list[1..3], list[1..]",
        "MATCH (n) RETURN n.count, n.exists IS NULL",
        "WITH {exists: 42} AS map RETURN 'exists' IN keys(map)",
        "MATCH (n) RETURN [p = (n)-->() | p]",
        "MATCH (n) RETURN count(n) AS count",
    ],
)
def test_oc9_grammar_extensions_parse(query: str) -> None:
    tree = cypherast.parse_one(query)
    assert tree.cypher(dialect="opencypher")


def test_label_predicate_filters() -> None:
    g = Graph()
    cypherast.run(
        "CREATE (:A {id: 0})<-[:ADMIN]-(:B {id: 1})-[:ADMIN]->(:C {id: 2})",
        graph=g,
    )
    rows = list(
        cypherast.run(
            "MATCH (a)-[:ADMIN]-(b) WHERE a:A RETURN a.id AS aid, b.id AS bid",
            graph=g,
        )
    )
    assert {r["aid"] for r in rows} == {0}


def test_list_slice_executor() -> None:
    g = Graph()
    rows = list(cypherast.run("WITH [1, 2, 3, 4, 5] AS list RETURN list[1..3] AS r", graph=g))
    assert rows[0]["r"] == [2, 3]
