#!/usr/bin/env python3
"""Parse-smoke generator from openCypher grammar snippets (non-TCK oracle).

Reads ``tools/grammar_smoke_queries.txt`` (one query per line, ``#`` comments)
and reports parse failures. Extend the file as BNF coverage grows.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cypherast.parser import Parser

QUERIES_FILE = Path(__file__).parent / "grammar_smoke_queries.txt"


def main() -> int:
    if not QUERIES_FILE.exists():
        print(f"missing {QUERIES_FILE}", file=sys.stderr)
        return 1
    lines = [
        ln.strip()
        for ln in QUERIES_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    failed = 0
    for q in lines:
        try:
            Parser(q).parse()
        except Exception as e:  # noqa: BLE001
            print(f"FAIL: {q!r} -> {e}")
            failed += 1
    total = len(lines)
    print(f"grammar smoke: {total - failed}/{total} parsed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
