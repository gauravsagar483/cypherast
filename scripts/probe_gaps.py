"""Probe cypherast(puppygraph) accept/reject vs the live PuppyGraph engine.

Prints one line per probe so the results can be diffed against engine output.
"""

from __future__ import annotations

import json
import sys

import cypherast as ca

PROBES: dict[str, str] = {
    # temporal constructors
    "date_str": "RETURN date('2026-08-10') AS x",
    "date_none": "RETURN date() AS x",
    "date_map": "RETURN date({year: 2026, month: 8, day: 10}) AS x",
    "datetime_none": "RETURN datetime() AS x",
    "datetime_str": "RETURN datetime('2026-08-10T00:00:00Z') AS x",
    "localdatetime": "RETURN localdatetime() AS x",
    "time": "RETURN time() AS x",
    "localtime": "RETURN localtime() AS x",
    "duration_map": "RETURN duration({days: 3}) AS x",
    "duration_str": "RETURN duration('P3D') AS x",
    "duration_between": "RETURN duration.between(date('2026-01-01'), date('2026-08-10')) AS x",
    "duration_indays": "RETURN duration.inDays(date('2026-01-01'), date('2026-08-10')) AS x",
    "date_truncate": "RETURN date.truncate('month', date('2026-08-10')) AS x",
    "datetime_truncate": "RETURN datetime.truncate('day', datetime()) AS x",
    "temporal_component": "RETURN date('2026-08-10').year AS x",
    "temporal_arith": "RETURN date('2026-08-10') + duration({days: 1}) AS x",
    # string / value coercion
    "tostringornull": "RETURN toStringOrNull(1) AS x",
    "tointegerornull": "RETURN toIntegerOrNull('x') AS x",
    "tofloatornull": "RETURN toFloatOrNull('x') AS x",
    "tobooleanornull": "RETURN toBooleanOrNull('x') AS x",
    "isempty_str": "RETURN isEmpty('') AS x",
    "char_length": "RETURN char_length('abc') AS x",
    "randomuuid": "RETURN randomUUID() AS x",
    "valuetype": "RETURN valueType(1) AS x",
    "normalize": "RETURN normalize('abc') AS x",
    "isnan": "RETURN isNaN(1.0) AS x",
    "nullif": "RETURN nullIf(1, 1) AS x",
    "tostring_list": "RETURN toStringList(['1']) AS x",
    # predicate / comprehension functions
    "exists_fn": "MATCH (n:DataQualityCheck) WHERE exists(n.overall_status) RETURN count(*) AS x",
    "all_fn": "RETURN all(v IN [1, 2] WHERE v > 0) AS x",
    "any_fn": "RETURN any(v IN [1, 2] WHERE v > 1) AS x",
    "none_fn": "RETURN none(v IN [1, 2] WHERE v > 5) AS x",
    "single_fn": "RETURN single(v IN [1, 2] WHERE v > 1) AS x",
    "reduce_fn": "RETURN reduce(acc = 0, v IN [1, 2] | acc + v) AS x",
    "list_comp": "RETURN [v IN [1, 2] WHERE v > 1 | v * 2] AS x",
    "exists_subquery": "MATCH (n:DataQualityCheck) WHERE EXISTS { (n) } RETURN count(*) AS x",
    "count_subquery": "MATCH (n:DataQualityCheck) RETURN count { (n) } AS x",
    # list ops
    "list_concat": "RETURN [1] + [2] AS x",
    "list_slice": "RETURN [1, 2, 3][0..2] AS x",
    "list_in": "RETURN 1 IN [1, 2] AS x",
    "range_step": "RETURN range(1, 10, 2) AS x",
    # projection / ordering shapes
    "order_by_source_var": (
        "MATCH (n:DataQualityCheck) RETURN n.source_table_id AS s ORDER BY n.last_run_date DESC"
    ),
    "distinct_with_agg": "MATCH (n:DataQualityCheck) RETURN DISTINCT count(*) AS x",
    "mixed_agg": "MATCH (n:DataQualityCheck) RETURN n.total_checks + count(*) AS x",
    "nulls_last": "MATCH (n:DataQualityCheck) RETURN n.total_checks AS t ORDER BY t DESC NULLS LAST",
    "two_collect_distinct": (
        "MATCH (n:DataQualityCheck) "
        "RETURN collect(DISTINCT n.overall_status) AS a, collect(DISTINCT n.total_checks) AS b"
    ),
    "unlabelled": "MATCH (n) RETURN count(*) AS x",
    "undirected": "MATCH (a:DataQualityCheck)--(b:DataQualityCheck) RETURN count(*) AS x",
    "call_subquery": "CALL { MATCH (n:DataQualityCheck) RETURN n LIMIT 1 } RETURN count(*) AS x",
    "union_all": (
        "MATCH (n:DataQualityCheck) RETURN n.total_checks AS x "
        "UNION ALL MATCH (m:DataQualityCheck) RETURN m.failed_checks AS x"
    ),
    "case_when": (
        "MATCH (n:DataQualityCheck) "
        "RETURN CASE WHEN n.failed_checks > 0 THEN 'bad' ELSE 'ok' END AS x LIMIT 1"
    ),
    "map_projection": "MATCH (n:DataQualityCheck) RETURN n {.overall_status} AS x LIMIT 1",
    "with_where": (
        "MATCH (n:DataQualityCheck) WITH n.overall_status AS s WHERE s = 'failed' "
        "RETURN count(*) AS x"
    ),
    "skip_limit": "MATCH (n:DataQualityCheck) RETURN n.total_checks AS x SKIP 1 LIMIT 2",
    "starts_with": (
        "MATCH (n:DataQualityCheck) WHERE n.source_table_id STARTS WITH 'egdp' "
        "RETURN count(*) AS x"
    ),
    "regex_match": (
        "MATCH (n:DataQualityCheck) WHERE n.overall_status =~ 'fail.*' RETURN count(*) AS x"
    ),
    "labels_fn": "MATCH (n:DataQualityCheck) RETURN labels(n) AS x LIMIT 1",
    "keys_fn": "MATCH (n:DataQualityCheck) RETURN keys(n) AS x LIMIT 1",
    "properties_fn": "MATCH (n:DataQualityCheck) RETURN properties(n) AS x LIMIT 1",
    "elementid_fn": "MATCH (n:DataQualityCheck) RETURN elementId(n) AS x LIMIT 1",
    "param": "MATCH (n:DataQualityCheck) WHERE n.overall_status = $s RETURN count(*) AS x",
}


def probe(query: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        ca.parse_one(query, read="puppygraph")
        out["parse"] = "ok"
    except Exception as exc:  # noqa: BLE001 - probe script
        out["parse"] = f"{type(exc).__name__}: {exc}".replace("\n", " ")
        return out
    try:
        ca.transpile(query, from_="puppygraph", to_="puppygraph", optimize=True)
        out["optimize"] = "ok"
    except Exception as exc:  # noqa: BLE001 - probe script
        out["optimize"] = f"{type(exc).__name__}: {exc}".replace("\n", " ")
    return out


def main() -> int:
    results = {name: probe(q) for name, q in PROBES.items()}
    json.dump(
        {"probes": PROBES, "cypherast": results},
        sys.stdout,
        indent=2,
    )
    print()
    for name, res in results.items():
        status = "OK  " if res.get("optimize") == "ok" else "FAIL"
        detail = res.get("optimize") if res.get("parse") == "ok" else f"PARSE {res['parse']}"
        print(f"{status} {name}: {detail}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
