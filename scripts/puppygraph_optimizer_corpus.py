#!/usr/bin/env python3
"""Corpus: ~50 Cypher queries → optimize read/write puppygraph (cypherast).

Inspired by PuppyGraph openCypher tutorial shapes (person/software modern graph)
and common Cypher patterns from PuppyGraph Cypher reference docs.

Run against published wheel::

    uv run --with cypherast==0.1.0 python scripts/puppygraph_optimizer_corpus.py

Or editable tree::

    uv run python scripts/puppygraph_optimizer_corpus.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field

DIALECT = "puppygraph"

# 50 queries: labelled nodes, LIMIT-friendly, modern graph labels (person/software).
QUERIES: list[tuple[str, str]] = [
    # --- docs hello / basics (1-10) ---
    ("hello_all_nodes", "MATCH (v:person) RETURN v LIMIT 20"),
    ("hello_all_edges", "MATCH ()-[e:knows]->() RETURN e LIMIT 20"),
    ("hello_count_nodes", "MATCH (v:person) RETURN count(v) AS c"),
    ("hello_count_edges", "MATCH ()-[e:created]->() RETURN count(e) AS c"),
    ("label_person", "MATCH (v:person) RETURN v.name, v.age LIMIT 20"),
    ("label_software", "MATCH (v:software) RETURN v.name, v.lang LIMIT 20"),
    ("prop_map_match", "MATCH (v:person {name: 'marko'}) RETURN v LIMIT 5"),
    ("where_age", "MATCH (v:person) WHERE v.age > 30 RETURN v.name, v.age LIMIT 20"),
    ("where_lang", "MATCH (p:person)-[:created]->(s:software) WHERE s.lang = 'java' RETURN p.name, s.name LIMIT 20"),
    ("element_id", "MATCH (v:person) RETURN elementId(v) AS id LIMIT 20"),
    # --- pattern / friends (11-20) ---
    ("created_pair", "MATCH (p:person)-[:created]->(s:software) RETURN p.name, s.name LIMIT 20"),
    ("knows_pair", "MATCH (a:person)-[:knows]->(b:person) RETURN a.name, b.name LIMIT 20"),
    ("co_creators", "MATCH (u:person {name:'marko'})-[:created]->(:software)<-[:created]-(v:person) RETURN v.name LIMIT 20"),
    ("varlen_created2", "MATCH (u:person {name:'marko'})-[:created*2]-(v:software) RETURN v.name LIMIT 20"),
    ("varlen_knows", "MATCH (a:person)-[:knows*1..3]->(b:person) RETURN a.name, b.name LIMIT 20"),
    ("undirected_knows", "MATCH (a:person)-[:knows]-(b:person) RETURN a.name, b.name LIMIT 20"),
    ("path_bind", "MATCH p=(u:person)-[:knows]->(v:person) RETURN p LIMIT 10"),
    ("with_pipe", "MATCH (:person {name: 'marko'})-[:knows]->(v:person) WITH v MATCH (v)-[:created]->(x:software) RETURN v.name AS otherPerson, x.name AS Software LIMIT 20"),
    ("optional_knows", "MATCH (a:person) OPTIONAL MATCH (a)-[:knows]->(b:person) RETURN a.name, b.name LIMIT 20"),
    ("multi_rel_types", "MATCH (a:person)-[:knows|created]->(b) RETURN a.name, labels(b) AS labs LIMIT 20"),
    # --- projection / lists / unwind (21-30) ---
    ("return_props", "MATCH (v:person) WHERE v.age > 30 RETURN v.name, v.age LIMIT 20"),
    ("list_literal_filter", "MATCH (v:person) WHERE v.name IN ['marko', 'josh', 'peter'] AND v.age > 30 RETURN v.name, v.age LIMIT 20"),
    ("list_projection", "MATCH (v:person) WHERE v.age > 30 RETURN [v.name, v.age] AS pair LIMIT 20"),
    ("unwind_list", "UNWIND ['a', 'b', 'b'] AS x RETURN x"),
    ("unwind_distinct", "UNWIND ['a', 'b', 'b'] AS x RETURN DISTINCT x"),
    ("skip_limit", "MATCH (v:person) RETURN v.name SKIP 1 LIMIT 2"),
    ("order_by", "MATCH (v:person) RETURN v.name, v.age ORDER BY v.age DESC LIMIT 10"),
    ("order_by_skip", "MATCH (v:person) RETURN v.name ORDER BY v.name SKIP 1 LIMIT 3"),
    ("map_projection", "MATCH (v:person) RETURN v {.name, .age} AS row LIMIT 20"),
    ("as_alias", "MATCH (v:person) RETURN v.name AS personName LIMIT 20"),
    # --- aggregation (31-40) ---
    ("count_by_software", "MATCH (p:person)-[:created]->(s:software) RETURN s.name AS sw, count(p) AS creators ORDER BY creators DESC LIMIT 20"),
    ("avg_age", "MATCH (v:person) RETURN avg(v.age) AS avgAge"),
    ("min_max_age", "MATCH (v:person) RETURN min(v.age) AS youngest, max(v.age) AS oldest"),
    ("sum_weight", "MATCH ()-[e:knows]->() RETURN sum(e.weight) AS totalWeight"),
    ("collect_names", "MATCH (v:person) RETURN collect(v.name) AS names LIMIT 1"),
    ("collect_distinct", "MATCH (a:person)-[:knows]->(b:person) RETURN a.name, collect(DISTINCT b.name) AS friends LIMIT 20"),
    ("two_collect_distinct", "MATCH (a:person)-[:created]->(s:software)<-[:created]-(b:person) WHERE a.name < b.name RETURN count(DISTINCT a.name) AS lefts, count(DISTINCT b.name) AS rights LIMIT 20"),
    ("distinct_with_count", "MATCH (a:person)-[:knows]->(b:person) WITH a.name AS n, count(b) AS c RETURN n, c LIMIT 20"),
    ("with_agg_filter", "MATCH (p:person)-[:created]->(s:software) WITH s, count(p) AS c WHERE c >= 1 RETURN s.name, c ORDER BY c DESC LIMIT 20"),
    ("count_star", "MATCH (v:person) RETURN count(*) AS n"),
    # --- predicates / exists-style / cartesian stress (41-50) ---
    ("pattern_pred_not", "MATCH (n:person) WHERE NOT (n)-[:knows]->(:person) RETURN n.name LIMIT 20"),
    ("pattern_pred_pos", "MATCH (n:person) WHERE (n)-[:created]->(:software) RETURN n.name LIMIT 20"),
    ("cartesian_persons", "MATCH (a:person) MATCH (b:person) WHERE a.name < b.name RETURN a.name, b.name LIMIT 20"),
    ("cartesian_person_soft", "MATCH (a:person) MATCH (s:software) RETURN a.name, s.name LIMIT 20"),
    ("pushdown_eq", "MATCH (n:person) WHERE n.status = 'ACTIVE' AND n.age > 21 RETURN n.name LIMIT 20"),
    ("pushdown_multi", "MATCH (n:person)-[:knows]->(m:person) WHERE n.name = 'marko' AND m.age > 30 RETURN m.name LIMIT 20"),
    ("unbounded_star", "MATCH (a:person)-[:knows*1..5]->(b:person) RETURN a.name, b.name LIMIT 20"),
    ("merge_chain_shape", "MATCH (a:person {name:'marko'}) MATCH (a)-[:knows]->(b:person) RETURN a.name, b.name LIMIT 20"),
    ("return_labels_type", "MATCH (a:person)-[r:knows]->(b:person) RETURN labels(a) AS al, type(r) AS rt, b.name LIMIT 20"),
    ("complex_with", "MATCH (p:person)-[:knows]->(f:person) WITH p, count(f) AS fc WHERE fc >= 1 MATCH (p)-[:created]->(s:software) RETURN p.name, fc, s.name LIMIT 20"),
]


@dataclass
class Row:
    id: str
    ok: bool
    parse_ok: bool
    optimize_ok: bool
    render_ok: bool
    changed: bool
    issue_count: int = 0
    issue_codes: list[str] = field(default_factory=list)
    error: str | None = None
    original: str = ""
    optimized: str = ""
    notes: list[str] = field(default_factory=list)


def _notes(before: str, after: str) -> list[str]:
    notes: list[str] = []
    bu, au = before.upper(), after.upper()
    if "LIMIT" not in bu and "LIMIT" in au:
        notes.append("injected_LIMIT")
    if bu.count("MATCH") < au.count("MATCH") and "," in before.split("RETURN")[0]:
        notes.append("split_cartesian_MATCH")
    if "{STATUS:" in au.replace(" ", "").upper() or "{status:" in after.replace(" ", ""):
        notes.append("property_pushdown")
    if "COLLECT(DISTINCT" in bu and after.upper().count("COLLECT(DISTINCT") < bu.count(
        "COLLECT(DISTINCT"
    ):
        notes.append("capped_collect_distinct")
    if (
        "DISTINCT" in bu.split("RETURN")[-1]
        and "COUNT(" in bu.upper()
        and "DISTINCT" not in after.upper().split("RETURN")[-1].split("LIMIT")[0]
    ):
        notes.append("dropped_DISTINCT_with_agg")
    if "EXISTS" in au:
        notes.append("emitted_EXISTS")
    return notes


def run_one(qid: str, cypher: str) -> Row:
    import cypherast

    row = Row(
        id=qid,
        ok=False,
        parse_ok=False,
        optimize_ok=False,
        render_ok=False,
        changed=False,
        original=cypher,
    )
    try:
        tree = cypherast.parse_one(cypher, read=DIALECT)
        row.parse_ok = True
        opt = cypherast.optimize(tree, read=DIALECT, write=DIALECT)
        row.optimize_ok = True
        out = opt.cypher(dialect=DIALECT, pretty=False)
        row.render_ok = True
        row.optimized = out
        row.changed = out.replace(" ", "").replace("\n", "") != cypher.replace(" ", "").replace(
            "\n", ""
        )
        issues = cypherast.validate(opt, read=DIALECT, dialect=DIALECT)
        row.issue_count = len(issues)
        row.issue_codes = [getattr(i, "code", type(i).__name__) for i in issues]
        row.notes = _notes(cypher, out)
        row.ok = row.parse_ok and row.optimize_ok and row.render_ok
    except Exception as e:  # noqa: BLE001 — corpus harness
        row.error = f"{type(e).__name__}: {e}"
    return row


def main() -> int:
    assert len(QUERIES) == 50, f"expected 50 queries, got {len(QUERIES)}"
    rows = [run_one(qid, q) for qid, q in QUERIES]
    ok = sum(1 for r in rows if r.ok)
    parse_ok = sum(1 for r in rows if r.parse_ok)
    changed = sum(1 for r in rows if r.changed)
    with_issues = sum(1 for r in rows if r.issue_count)
    failed = [r for r in rows if not r.ok]

    note_hist: dict[str, int] = {}
    for r in rows:
        for n in r.notes:
            note_hist[n] = note_hist.get(n, 0) + 1

    summary = {
        "package": "cypherast",
        "dialect": f"{DIALECT}->{DIALECT}",
        "total": len(rows),
        "ok": ok,
        "parse_ok": parse_ok,
        "optimize_render_ok": ok,
        "changed": changed,
        "unchanged": len(rows) - changed,
        "with_validate_issues": with_issues,
        "failed": len(failed),
        "rewrite_notes": note_hist,
        "failures": [{"id": r.id, "error": r.error, "query": r.original} for r in failed],
        "rows": [asdict(r) for r in rows],
    }

    out_path = "scripts/puppygraph_optimizer_corpus_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"total={summary['total']} ok={ok} parse_ok={parse_ok} changed={changed} validate_issues={with_issues}")
    print(f"rewrite_notes={note_hist}")
    if failed:
        print("FAILURES:")
        for r in failed:
            print(f"  - {r.id}: {r.error}")
    print(f"wrote {out_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
