"""Second-pass verification of capability flags that the first probe contradicted.

    uv run --with neo4j python scripts/probe_verify.py
"""

from __future__ import annotations

import json
import os
import sys

from neo4j import GraphDatabase  # type: ignore[import-not-found]

CHECKS: dict[str, str] = {
    "list_comp_rows": "MATCH (n:DataQualityCheck) RETURN [v IN [1,2] WHERE v > 1 | v * 2] AS x LIMIT 1",
    "list_concat_rows": "RETURN [1] + [2] AS x",
    "list_concat_prop": "MATCH (n:DataQualityCheck) RETURN [n.overall_status] + ['z'] AS x LIMIT 1",
    "undirected_rows": "MATCH (a:DataQualityCheck)--(b) RETURN count(*) AS x",
    "call_subquery_rows": "CALL { MATCH (n:DataQualityCheck) RETURN n.total_checks AS t LIMIT 1 } RETURN t",
    "exists_fn_rows": "MATCH (n:DataQualityCheck) WHERE exists(n.overall_status) RETURN count(*) AS x",
    "regex_rows": "MATCH (n:DataQualityCheck) WHERE n.overall_status =~ 'fail.*' RETURN count(*) AS x",
    "bare_node_rows": "MATCH (n) RETURN count(*) AS x",
    "synthetic_label": "MATCH (n:_Node) RETURN count(*) AS x",
    "map_projection": "MATCH (n:DataQualityCheck) RETURN n {.overall_status} AS x LIMIT 1",
    "nulls_last": "MATCH (n:DataQualityCheck) RETURN n.total_checks AS t ORDER BY t DESC NULLS LAST",
    "all_fn_rows": "MATCH (n:DataQualityCheck) WHERE all(v IN [1,2] WHERE v > 0) RETURN count(*) AS x",
    "single_fn_rows": "RETURN single(v IN [1,2] WHERE v > 1) AS x",
    "range_step_rows": "RETURN range(1, 10, 2) AS x",
    "id_contains": "MATCH (n:DataQualityCheck) WHERE toString(id(n)) CONTAINS 'x' RETURN count(*) AS x",
    "node_in_list": "MATCH (n:DataQualityCheck) WITH collect(n) AS ns, n AS one RETURN one IN ns AS x LIMIT 1",
    "date_compare_string": "MATCH (n:DataQualityCheck) WHERE n.last_run_date >= '2026-08-10' RETURN count(*) AS x",
    "order_by_alias_only": "MATCH (n:DataQualityCheck) RETURN n.total_checks AS t ORDER BY t DESC LIMIT 2",
}


def main() -> int:
    out: dict[str, object] = {}
    driver = GraphDatabase.driver(
        os.environ.get("PUPPY_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("PUPPY_USER", "puppygraph"),
            os.environ.get("PUPPY_PASSWORD", "puppygraph123"),
        ),
    )
    with driver.session(database=os.environ.get("PUPPY_DB", "default")) as session:
        for name, query in CHECKS.items():
            try:
                rows = [r.data() for r in session.run(query)][:2]
                out[name] = {"ok": True, "rows": rows}
            except Exception as exc:  # noqa: BLE001 - probe script
                msg = str(exc).replace("\n", " ")
                marker = "message:"
                idx = msg.find(marker)
                out[name] = {
                    "ok": False,
                    "error": (msg[idx : idx + 140] if idx >= 0 else msg[:140]),
                }
    driver.close()
    json.dump(out, sys.stdout, indent=2, default=str)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
