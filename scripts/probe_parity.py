"""Compare cypherast's PuppyGraph target with the live PuppyGraph engine.

Run with an ephemeral Bolt driver:
    uv run --with neo4j python scripts/probe_parity.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from neo4j import GraphDatabase  # type: ignore[import-not-found]

import cypherast

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from puppy_surface_probe import probes, short_err  # noqa: E402


def main() -> int:
    driver = GraphDatabase.driver(
        os.environ.get("PUPPY_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("PUPPY_USER", "puppygraph"),
            os.environ.get("PUPPY_PASSWORD", "puppygraph123"),
        ),
    )
    database = os.environ.get("PUPPY_DB", "default")
    results: list[dict[str, Any]] = []
    with driver.session(database=database) as session:
        for probe in probes():
            row: dict[str, Any] = {
                "category": probe.category,
                "subcategory": probe.subcategory,
                "name": probe.name,
                "source": probe.query,
            }
            try:
                rendered = cypherast.translate(
                    probe.query,
                    from_="puppygraph",
                    to_="puppygraph",
                    optimize=True,
                )
                row["cypherast"] = "accepted"
                row["rendered"] = rendered
            except Exception as exc:  # noqa: BLE001 - deliberate probe boundary
                row["cypherast"] = "rejected"
                row["cypherast_error"] = f"{type(exc).__name__}: {exc}".replace(
                    "\n", " "
                )[:220]
                results.append(row)
                continue
            try:
                list(session.run(rendered, **(probe.params or {})))
                row["engine"] = "accepted"
            except Exception as exc:  # noqa: BLE001 - deliberate probe boundary
                row["engine"] = "rejected"
                row["engine_error"] = short_err(exc)
            results.append(row)
    driver.close()

    accepted = [r for r in results if r["cypherast"] == "accepted"]
    emitted_failures = [r for r in accepted if r.get("engine") == "rejected"]
    summary = {
        "total": len(results),
        "cypherast_accepted": len(accepted),
        "cypherast_rejected": len(results) - len(accepted),
        "accepted_output_engine_failures": len(emitted_failures),
    }
    json.dump({"summary": summary, "results": results}, sys.stdout, indent=2)
    print()
    print(json.dumps(summary), file=sys.stderr)
    for result in emitted_failures:
        print(
            f"EMITTED_FAIL {result['category']}/{result['name']}: "
            f"{result.get('engine_error')}",
            file=sys.stderr,
        )
    return 1 if emitted_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
