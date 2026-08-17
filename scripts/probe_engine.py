"""Run the probe battery against the live PuppyGraph bolt endpoint.

Throwaway: run with an ephemeral driver, e.g.
    uv run --with neo4j python scripts/probe_engine.py
"""

from __future__ import annotations

import json
import os
import sys

from neo4j import GraphDatabase  # type: ignore[import-not-found]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_gaps import PROBES  # noqa: E402

URI = os.environ.get("PUPPY_URI", "bolt://localhost:7687")
USER = os.environ.get("PUPPY_USER", "puppygraph")
PASSWORD = os.environ.get("PUPPY_PASSWORD", "puppygraph123")


def main() -> int:
    results: dict[str, str] = {}
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    with driver.session(database=os.environ.get("PUPPY_DB", "default")) as session:
        for name, query in PROBES.items():
            params = {"s": "failed"} if "$s" in query else {}
            try:
                session.run(query, **params).consume()
                results[name] = "ok"
            except Exception as exc:  # noqa: BLE001 - probe script
                msg = f"{type(exc).__name__}: {exc}".replace("\n", " ")
                results[name] = msg[:220]
    driver.close()
    json.dump(results, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
