"""Full PuppyGraph Cypher surface probe (throwaway).

Runs openCypher-9-ish constructs against bolt://localhost:7687 and prints JSON.
  uv run --with neo4j python scripts/puppy_surface_probe.py > /tmp/pg_surface.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass

from neo4j import GraphDatabase  # type: ignore[import-not-found]

URI = os.environ.get("PUPPY_URI", "bolt://localhost:7687")
USER = os.environ.get("PUPPY_USER", "puppygraph")
PASSWORD = os.environ.get("PUPPY_PASSWORD", "puppygraph123")
DB = os.environ.get("PUPPY_DB", "default")


@dataclass(frozen=True)
class Probe:
    category: str
    subcategory: str
    name: str
    query: str
    params: dict | None = None


def probes() -> list[Probe]:
    p: list[Probe] = []

    def add(cat: str, sub: str, name: str, q: str, params: dict | None = None) -> None:
        p.append(Probe(cat, sub, name, q, params))

    # ── Predicate functions ──────────────────────────────────────────────
    add("functions", "predicate", "all", "RETURN all(x IN [1,2,3] WHERE x > 0) AS x")
    add("functions", "predicate", "any", "RETURN any(x IN [1,2,3] WHERE x > 2) AS x")
    add("functions", "predicate", "exists_prop", "MATCH (n) WHERE exists(n._label) RETURN count(*) AS x LIMIT 1")
    add("functions", "predicate", "exists_pattern_legacy", "MATCH (n) WHERE exists((n)-->()) RETURN count(*) AS x LIMIT 1")
    add("functions", "predicate", "none", "RETURN none(x IN [1,2,3] WHERE x > 10) AS x")
    add("functions", "predicate", "single", "RETURN single(x IN [1,2,3] WHERE x = 2) AS x")

    # ── Scalar functions ─────────────────────────────────────────────────
    add("functions", "scalar", "coalesce", "RETURN coalesce(null, 1, 2) AS x")
    add("functions", "scalar", "coalesce_2", "RETURN coalesce(null, 2) AS x")
    add("functions", "scalar", "endNode", "MATCH ()-[r]->() RETURN endNode(r) AS x LIMIT 1")
    add("functions", "scalar", "head", "RETURN head([1,2,3]) AS x")
    add("functions", "scalar", "id", "MATCH (n) RETURN id(n) AS x LIMIT 1")
    add("functions", "scalar", "last", "RETURN last([1,2,3]) AS x")
    add("functions", "scalar", "length_path", "MATCH p=()-->() RETURN length(p) AS x LIMIT 1")
    add("functions", "scalar", "properties", "MATCH (n) RETURN properties(n) AS x LIMIT 1")
    add("functions", "scalar", "size_list", "RETURN size([1,2,3]) AS x")
    add("functions", "scalar", "size_string", "RETURN size('abc') AS x")
    add("functions", "scalar", "startNode", "MATCH ()-[r]->() RETURN startNode(r) AS x LIMIT 1")
    add("functions", "scalar", "timestamp", "RETURN timestamp() AS x")
    add("functions", "scalar", "toBoolean", "RETURN toBoolean('true') AS x")
    add("functions", "scalar", "toFloat", "RETURN toFloat('1.5') AS x")
    add("functions", "scalar", "toInteger", "RETURN toInteger('7') AS x")
    add("functions", "scalar", "toString", "RETURN toString(42) AS x")
    add("functions", "scalar", "type", "MATCH ()-[r]->() RETURN type(r) AS x LIMIT 1")
    add("functions", "scalar", "elementId", "MATCH (n) RETURN elementId(n) AS x LIMIT 1")
    add("functions", "scalar", "keys", "MATCH (n) RETURN keys(n) AS x LIMIT 1")
    add("functions", "scalar", "labels", "MATCH (n) RETURN labels(n) AS x LIMIT 1")
    # Neo4j extras often seen in engines
    add("functions", "scalar", "nullIf", "RETURN nullIf(1, 1) AS x")
    add("functions", "scalar", "randomUUID", "RETURN randomUUID() AS x")
    add("functions", "scalar", "valueType", "RETURN valueType(1) AS x")
    add("functions", "scalar", "isEmpty_str", "RETURN isEmpty('') AS x")
    add("functions", "scalar", "isEmpty_list", "RETURN isEmpty([]) AS x")
    add("functions", "scalar", "isNaN", "RETURN isNaN(0.0/0.0) AS x")
    add("functions", "scalar", "toStringOrNull", "RETURN toStringOrNull(1) AS x")
    add("functions", "scalar", "toIntegerOrNull", "RETURN toIntegerOrNull('x') AS x")
    add("functions", "scalar", "toFloatOrNull", "RETURN toFloatOrNull('x') AS x")
    add("functions", "scalar", "toBooleanOrNull", "RETURN toBooleanOrNull('x') AS x")

    # ── Aggregating functions ────────────────────────────────────────────
    add("functions", "aggregating", "avg", "MATCH (n) RETURN avg(toFloat(1)) AS x")
    add("functions", "aggregating", "collect", "MATCH (n) RETURN collect(n) AS x LIMIT 1")
    add("functions", "aggregating", "collect_distinct", "MATCH (n) RETURN collect(DISTINCT labels(n)[0]) AS x")
    add("functions", "aggregating", "count_star", "MATCH (n) RETURN count(*) AS x")
    add("functions", "aggregating", "count_expr", "MATCH (n) RETURN count(n) AS x")
    add("functions", "aggregating", "count_distinct", "MATCH (n) RETURN count(DISTINCT labels(n)[0]) AS x")
    add("functions", "aggregating", "max", "RETURN max(1) AS x")
    add("functions", "aggregating", "min", "RETURN min(1) AS x")
    add("functions", "aggregating", "percentileCont", "UNWIND [1.0,2.0,3.0] AS v RETURN percentileCont(v, 0.5) AS x")
    add("functions", "aggregating", "percentileDisc", "UNWIND [1.0,2.0,3.0] AS v RETURN percentileDisc(v, 0.5) AS x")
    add("functions", "aggregating", "stdev", "UNWIND [1.0,2.0,3.0] AS v RETURN stdev(v) AS x")
    add("functions", "aggregating", "stdevP", "UNWIND [1.0,2.0,3.0] AS v RETURN stdevP(v) AS x")
    add("functions", "aggregating", "sum", "UNWIND [1,2,3] AS v RETURN sum(v) AS x")

    # ── List functions ───────────────────────────────────────────────────
    add("functions", "list", "range_2", "RETURN range(1, 3) AS x")
    add("functions", "list", "range_3", "RETURN range(1, 10, 2) AS x")
    add("functions", "list", "reverse_list", "RETURN reverse([1,2,3]) AS x")
    add("functions", "list", "tail", "RETURN tail([1,2,3]) AS x")
    add("functions", "list", "nodes", "MATCH p=()-->() RETURN nodes(p) AS x LIMIT 1")
    add("functions", "list", "relationships", "MATCH p=()-->() RETURN relationships(p) AS x LIMIT 1")
    add("functions", "list", "labels_fn", "MATCH (n) RETURN labels(n) AS x LIMIT 1")
    add("functions", "list", "keys_fn", "MATCH (n) RETURN keys(n) AS x LIMIT 1")
    add("functions", "list", "toStringList", "RETURN toStringList([1,2]) AS x")
    add("functions", "list", "reduce", "RETURN reduce(s = 0, x IN [1,2,3] | s + x) AS x")
    add("functions", "list", "extract_legacy", "RETURN extract(x IN [1,2,3] | x * 2) AS x")
    add("functions", "list", "filter_legacy", "RETURN filter(x IN [1,2,3] WHERE x > 1) AS x")

    # ── Math numeric ─────────────────────────────────────────────────────
    for name, q in [
        ("abs", "RETURN abs(-3) AS x"),
        ("ceil", "RETURN ceil(1.1) AS x"),
        ("floor", "RETURN floor(1.9) AS x"),
        ("round", "RETURN round(1.5) AS x"),
        ("sign", "RETURN sign(-5) AS x"),
        ("rand", "RETURN rand() AS x"),
    ]:
        add("functions", "math_numeric", name, q)

    # ── Math logarithmic ─────────────────────────────────────────────────
    for name, q in [
        ("e", "RETURN e() AS x"),
        ("exp", "RETURN exp(1) AS x"),
        ("log", "RETURN log(10) AS x"),
        ("log10", "RETURN log10(100) AS x"),
        ("sqrt", "RETURN sqrt(9) AS x"),
    ]:
        add("functions", "math_log", name, q)

    # ── Math trigonometric ───────────────────────────────────────────────
    for name, q in [
        ("sin", "RETURN sin(0) AS x"),
        ("cos", "RETURN cos(0) AS x"),
        ("tan", "RETURN tan(0) AS x"),
        ("asin", "RETURN asin(0) AS x"),
        ("acos", "RETURN acos(1) AS x"),
        ("atan", "RETURN atan(0) AS x"),
        ("atan2", "RETURN atan2(1, 1) AS x"),
        ("cot", "RETURN cot(1) AS x"),
        ("degrees", "RETURN degrees(3.1415926535) AS x"),
        ("radians", "RETURN radians(180) AS x"),
        ("pi", "RETURN pi() AS x"),
        ("haversin", "RETURN haversin(1) AS x"),
    ]:
        add("functions", "math_trig", name, q)

    # ── String functions ─────────────────────────────────────────────────
    for name, q in [
        ("left", "RETURN left('abcdef', 3) AS x"),
        ("lTrim", "RETURN lTrim('  abc') AS x"),
        ("replace", "RETURN replace('abc', 'b', 'X') AS x"),
        ("reverse_str", "RETURN reverse('abc') AS x"),
        ("right", "RETURN right('abcdef', 3) AS x"),
        ("rTrim", "RETURN rTrim('abc  ') AS x"),
        ("split", "RETURN split('a,b,c', ',') AS x"),
        ("substring_2", "RETURN substring('abcdef', 2) AS x"),
        ("substring_3", "RETURN substring('abcdef', 1, 3) AS x"),
        ("toLower", "RETURN toLower('AbC') AS x"),
        ("toUpper", "RETURN toUpper('AbC') AS x"),
        ("trim", "RETURN trim('  abc  ') AS x"),
        ("char_length", "RETURN char_length('abc') AS x"),
        ("character_length", "RETURN character_length('abc') AS x"),
        ("normalize", "RETURN normalize('abc') AS x"),
    ]:
        add("functions", "string", name, q)

    # ── Temporal / spatial (engine extensions) ───────────────────────────
    for name, q in [
        ("date", "RETURN date('2026-08-10') AS x"),
        ("date_now", "RETURN date() AS x"),
        ("datetime", "RETURN datetime() AS x"),
        ("datetime_str", "RETURN datetime('2026-08-10T00:00:00Z') AS x"),
        ("localdatetime", "RETURN localdatetime() AS x"),
        ("time", "RETURN time() AS x"),
        ("localtime", "RETURN localtime() AS x"),
        ("duration_map", "RETURN duration({days: 3}) AS x"),
        ("duration_str", "RETURN duration('P3D') AS x"),
        ("duration_between", "RETURN duration.between(date('2026-01-01'), date('2026-08-10')) AS x"),
        ("duration_inDays", "RETURN duration.inDays(date('2026-01-01'), date('2026-08-10')) AS x"),
        ("date_truncate", "RETURN date.truncate('month', date('2026-08-10')) AS x"),
        ("point", "RETURN point({x: 1.0, y: 2.0}) AS x"),
        ("distance", "RETURN distance(point({x:0.0,y:0.0}), point({x:1.0,y:1.0})) AS x"),
    ]:
        add("functions", "temporal_spatial", name, q)

    # ── Path functions ───────────────────────────────────────────────────
    add("functions", "path", "shortestPath", "MATCH (a), (b) WHERE id(a) <> id(b) RETURN shortestPath((a)-[*..3]-(b)) AS x LIMIT 1")
    add("functions", "path", "allShortestPaths", "MATCH (a), (b) WHERE id(a) <> id(b) RETURN allShortestPaths((a)-[*..2]-(b)) AS x LIMIT 1")

    # ── Clauses ──────────────────────────────────────────────────────────
    add("clauses", "read", "MATCH", "MATCH (n) RETURN count(*) AS x")
    add("clauses", "read", "OPTIONAL_MATCH", "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN count(*) AS x")
    add("clauses", "read", "WHERE", "MATCH (n) WHERE true RETURN count(*) AS x")
    add("clauses", "read", "WITH", "MATCH (n) WITH n RETURN count(*) AS x")
    add("clauses", "read", "WITH_WHERE", "MATCH (n) WITH n WHERE true RETURN count(*) AS x")
    add("clauses", "read", "RETURN", "RETURN 1 AS x")
    add("clauses", "read", "RETURN_DISTINCT", "UNWIND [1,1,2] AS v RETURN DISTINCT v")
    add("clauses", "read", "ORDER_BY", "UNWIND [3,1,2] AS v RETURN v ORDER BY v")
    add("clauses", "read", "ORDER_BY_DESC", "UNWIND [3,1,2] AS v RETURN v ORDER BY v DESC")
    add("clauses", "read", "ORDER_BY_NULLS_LAST", "UNWIND [1, null, 2] AS v RETURN v ORDER BY v NULLS LAST")
    add("clauses", "read", "ORDER_BY_NULLS_FIRST", "UNWIND [1, null, 2] AS v RETURN v ORDER BY v NULLS FIRST")
    add("clauses", "read", "SKIP", "UNWIND range(1,5) AS v RETURN v SKIP 2")
    add("clauses", "read", "LIMIT", "UNWIND range(1,5) AS v RETURN v LIMIT 2")
    add("clauses", "read", "UNWIND", "UNWIND [1,2,3] AS v RETURN v")
    add("clauses", "read", "UNION", "RETURN 1 AS x UNION RETURN 2 AS x")
    add("clauses", "read", "UNION_ALL", "RETURN 1 AS x UNION ALL RETURN 1 AS x")
    add("clauses", "read", "CALL_subquery", "CALL { RETURN 1 AS t } RETURN t")
    add("clauses", "read", "CALL_procedure", "CALL db.labels() YIELD label RETURN label LIMIT 1")
    add("clauses", "read", "USE", "USE default MATCH (n) RETURN count(*) AS x")
    add("clauses", "write", "CREATE", "CREATE (n:__ProbeTmp {k: 1}) RETURN n")
    add("clauses", "write", "MERGE", "MERGE (n:__ProbeTmp {k: 999}) RETURN n")
    add("clauses", "write", "DELETE", "MATCH (n:__ProbeTmp {k: 999}) DELETE n RETURN count(*) AS x")
    add("clauses", "write", "DETACH_DELETE", "MATCH (n:__ProbeTmp) DETACH DELETE n RETURN count(*) AS x")
    add("clauses", "write", "SET", "MATCH (n) WHERE false SET n.x = 1 RETURN count(*) AS x")
    add("clauses", "write", "REMOVE", "MATCH (n) WHERE false REMOVE n.x RETURN count(*) AS x")
    add("clauses", "write", "FOREACH", "FOREACH (x IN [1] | CREATE (:__ProbeTmp {k: x}))")
    add("clauses", "admin", "LOAD_CSV", "LOAD CSV FROM 'file:///tmp/x.csv' AS row RETURN row LIMIT 1")
    add("clauses", "admin", "CREATE_INDEX", "CREATE INDEX ON :Person(name)")
    add("clauses", "admin", "DROP_INDEX", "DROP INDEX ON :Person(name)")
    add("clauses", "admin", "CREATE_CONSTRAINT", "CREATE CONSTRAINT ON (n:Person) ASSERT n.name IS UNIQUE")
    add("clauses", "cypher25", "FILTER", "MATCH (n) FILTER WHERE true RETURN count(*) AS x")
    add("clauses", "cypher25", "LET", "LET x = 1 RETURN x")
    add("clauses", "cypher25", "WHEN", "WHEN true THEN RETURN 1 AS x ELSE RETURN 0 AS x")

    # ── Operators ────────────────────────────────────────────────────────
    for name, q in [
        ("eq", "RETURN 1 = 1 AS x"),
        ("neq_ltgt", "RETURN 1 <> 2 AS x"),
        ("neq_bang", "RETURN 1 != 2 AS x"),
        ("lt", "RETURN 1 < 2 AS x"),
        ("lte", "RETURN 1 <= 1 AS x"),
        ("gt", "RETURN 2 > 1 AS x"),
        ("gte", "RETURN 2 >= 2 AS x"),
        ("is_null", "RETURN null IS NULL AS x"),
        ("is_not_null", "RETURN 1 IS NOT NULL AS x"),
        ("and", "RETURN true AND false AS x"),
        ("or", "RETURN true OR false AS x"),
        ("xor", "RETURN true XOR false AS x"),
        ("not", "RETURN NOT false AS x"),
        ("in", "RETURN 1 IN [1,2,3] AS x"),
        ("starts_with", "RETURN 'abcdef' STARTS WITH 'abc' AS x"),
        ("ends_with", "RETURN 'abcdef' ENDS WITH 'def' AS x"),
        ("contains", "RETURN 'abcdef' CONTAINS 'cd' AS x"),
        ("regex", "RETURN 'abc' =~ 'a.*' AS x"),
        ("plus_num", "RETURN 1 + 2 AS x"),
        ("minus_num", "RETURN 5 - 2 AS x"),
        ("mul", "RETURN 3 * 4 AS x"),
        ("div", "RETURN 8 / 2 AS x"),
        ("mod", "RETURN 7 % 3 AS x"),
        ("pow", "RETURN 2 ^ 3 AS x"),
        ("unary_minus", "RETURN -3 AS x"),
        ("list_concat", "RETURN [1,2] + [3] AS x"),
        ("string_concat", "RETURN 'a' + 'b' AS x"),
        ("list_index", "RETURN [1,2,3][1] AS x"),
        ("list_slice", "RETURN [1,2,3,4][1..3] AS x"),
        ("map_dot", "RETURN {a: 1}.a AS x"),
        ("map_bracket", "WITH {a: 1} AS m RETURN m['a'] AS x"),
    ]:
        add("operators", "expression", name, q)

    # ── Expressions ──────────────────────────────────────────────────────
    add("expressions", "case", "CASE_simple", "RETURN CASE 1 WHEN 1 THEN 'one' ELSE 'other' END AS x")
    add("expressions", "case", "CASE_searched", "RETURN CASE WHEN 1 > 0 THEN 'yes' ELSE 'no' END AS x")
    add("expressions", "literal", "list_literal", "RETURN [1, 2, 3] AS x")
    add("expressions", "literal", "map_literal", "RETURN {a: 1, b: 'x'} AS x")
    add("expressions", "literal", "null_literal", "RETURN null AS x")
    add("expressions", "literal", "bool_literal", "RETURN true AS x, false AS y")
    add("expressions", "comprehension", "list_comp", "RETURN [x IN [1,2,3] WHERE x > 1 | x * 2] AS x")
    add("expressions", "comprehension", "list_comp_no_where", "RETURN [x IN [1,2,3] | x * 2] AS x")
    add("expressions", "comprehension", "pattern_comp", "MATCH (n) RETURN [(n)-->(m) | m] AS x LIMIT 1")
    add("expressions", "comprehension", "map_projection", "MATCH (n) RETURN n {.*} AS x LIMIT 1")
    add("expressions", "comprehension", "map_projection_props", "MATCH (n) RETURN n {.name} AS x LIMIT 1")
    add("expressions", "subquery", "EXISTS_subquery", "MATCH (n) WHERE EXISTS { (n)-->() } RETURN count(*) AS x")
    add("expressions", "subquery", "COUNT_subquery", "MATCH (n) RETURN count { (n)-->() } AS x LIMIT 1")
    add("expressions", "pattern_pred", "pattern_in_WHERE", "MATCH (n) WHERE (n)-->() RETURN count(*) AS x")
    add("expressions", "pattern_pred", "NOT_pattern_in_WHERE", "MATCH (n) WHERE NOT (n)-->() RETURN count(*) AS x")

    # ── Patterns ─────────────────────────────────────────────────────────
    add("patterns", "node", "bare_node", "MATCH (n) RETURN count(*) AS x")
    add("patterns", "node", "labelled_node", "MATCH (n:_ProbeNoSuch) RETURN count(*) AS x")
    add("patterns", "node", "multi_label", "MATCH (n:A:B) RETURN count(*) AS x")
    add("patterns", "node", "label_or", "MATCH (n:A|B) RETURN count(*) AS x")
    add("patterns", "node", "prop_map", "MATCH (n {k: 1}) RETURN count(*) AS x")
    add("patterns", "rel", "directed_out", "MATCH ()-[]->() RETURN count(*) AS x")
    add("patterns", "rel", "directed_in", "MATCH ()<-[]-() RETURN count(*) AS x")
    add("patterns", "rel", "undirected", "MATCH ()--() RETURN count(*) AS x")
    add("patterns", "rel", "typed_rel", "MATCH ()-[:__NoSuchRel]->() RETURN count(*) AS x")
    add("patterns", "rel", "multi_type_rel", "MATCH ()-[:A|B]->() RETURN count(*) AS x")
    add("patterns", "rel", "var_length_fixed", "MATCH ()-[*2]->() RETURN count(*) AS x")
    add("patterns", "rel", "var_length_range", "MATCH ()-[*1..2]->() RETURN count(*) AS x")
    add("patterns", "rel", "var_length_unbounded", "MATCH ()-[*]->() RETURN count(*) AS x")
    add("patterns", "rel", "var_length_star_n", "MATCH ()-[*3]->() RETURN count(*) AS x")
    add("patterns", "path", "path_assign", "MATCH p=()-->() RETURN count(p) AS x")
    add("patterns", "path", "shortestPath_pattern", "MATCH (a), (b) WHERE id(a) <> id(b) WITH a,b LIMIT 1 MATCH p = shortestPath((a)-[*..2]-(b)) RETURN p")
    add("patterns", "multi", "comma_cartesian", "MATCH (a), (b) RETURN count(*) AS x LIMIT 1")
    add("patterns", "multi", "connected_multi", "MATCH (a), (a)-->(b) RETURN count(*) AS x LIMIT 1")

    # ── Variables / parameters ───────────────────────────────────────────
    add("variables", "binding", "alias_AS", "RETURN 1 AS answer")
    add("variables", "binding", "reuse_alias", "WITH 1 AS a RETURN a AS b")
    add("variables", "binding", "underscore_var", "RETURN 1 AS _x")
    add("variables", "binding", "backtick_var", "RETURN 1 AS `weird name`")
    add("variables", "params", "param_dollar", "RETURN $p AS x", {"p": 42})
    add("variables", "params", "param_in_WHERE", "MATCH (n) WHERE true RETURN $p AS x", {"p": "ok"})
    add("variables", "params", "param_list", "RETURN $xs AS x", {"xs": [1, 2, 3]})
    add("variables", "params", "param_map", "RETURN $m.a AS x", {"m": {"a": 7}})

    # ── Reserved keywords as identifiers ─────────────────────────────────
    keywords = [
        "MATCH", "RETURN", "WHERE", "WITH", "AS", "AND", "OR", "NOT", "XOR",
        "NULL", "TRUE", "FALSE", "IN", "IS", "CASE", "WHEN", "THEN", "ELSE",
        "END", "UNWIND", "UNION", "ALL", "DISTINCT", "ORDER", "BY", "ASC",
        "DESC", "SKIP", "LIMIT", "CREATE", "MERGE", "DELETE", "SET", "REMOVE",
        "OPTIONAL", "CALL", "YIELD", "USING", "INDEX", "CONSTRAINT", "UNIQUE",
        "DROP", "ON", "ASSERT", "STARTS", "ENDS", "CONTAINS", "COUNT",
        "EXISTS", "FILTER", "EXTRACT", "REDUCE", "FOREACH", "LOAD", "CSV",
        "FROM", "HEADERS", "PERIODIC", "COMMIT", "SCAN", "JOIN", "SHORTESTPATH",
        "ALLSHORTESTPATHS", "NODE", "RELATIONSHIP", "PATH", "GRAPH",
    ]
    for kw in keywords:
        # try as variable binding via backticks and bare (if allowed)
        add("keywords", "as_alias_backtick", kw, f"RETURN 1 AS `{kw}`")
        add("keywords", "as_alias_bare", kw, f"RETURN 1 AS {kw}")

    return p


def short_err(exc: Exception) -> str:
    msg = str(exc).replace("\n", " ")
    for pat in [
        r"\[FET-\d+\][^\]]*\]?",
        r"\[ET-\d+\][^\]]*\]?",
        r"\[TE-\d+\][^\]]*\]?",
        r"\[APT-\d+\][^\]]*\]?",
        r"\[PJT-\d+\][^\]]*\]?",
        r"Unsupported [^:]+",
        r"Invalid input '[^']+'",
        r"Type mismatch:[^.]+",
        r"Unknown function '[^']+'",
    ]:
        m = re.search(pat, msg, re.I)
        if m:
            return m.group(0)[:160]
    i = msg.find("message:")
    if i >= 0:
        return msg[i : i + 140]
    return msg[:140]


def main() -> int:
    all_probes = probes()
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    results = []
    with driver.session(database=DB) as session:
        for pr in all_probes:
            entry = asdict(pr)
            try:
                list(session.run(pr.query, **(pr.params or {})))
                entry["ok"] = True
                entry["error"] = None
            except Exception as exc:  # noqa: BLE001
                entry["ok"] = False
                entry["error"] = short_err(exc)
            results.append(entry)
            # best-effort cleanup of write probes
            if pr.name in {"CREATE", "MERGE", "FOREACH"}:
                with suppress(Exception):
                    session.run("MATCH (n:__ProbeTmp) DETACH DELETE n").consume()
    driver.close()

    summary: dict[str, dict[str, int]] = {}
    for r in results:
        key = f"{r['category']}/{r['subcategory']}"
        summary.setdefault(key, {"ok": 0, "fail": 0})
        summary[key]["ok" if r["ok"] else "fail"] += 1

    out = {
        "engine": URI,
        "database": DB,
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "fail": sum(1 for r in results if not r["ok"]),
        "summary": summary,
        "results": results,
    }
    json.dump(out, sys.stdout, indent=2)
    print()
    print(
        f"TOTAL {out['ok']}/{out['total']} ok, {out['fail']} fail",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
