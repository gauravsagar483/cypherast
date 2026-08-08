"""Run official openCypher TCK from /tmp checkout and write tests/tck/results.md."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from tests.tck.runner import run_official


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run official openCypher TCK against cypherast")
    p.add_argument("--parse-only", action="store_true", help="Parse gate only (no executor)")
    p.add_argument("--oc9-filter", action="store_true", help="Skip OC9-excluded scenarios")
    p.add_argument(
        "--dialect",
        default=os.environ.get("CYPHERAST_TCK_DIALECT", "opencypher"),
        help="Parse/read dialect (default: opencypher or CYPHERAST_TCK_DIALECT)",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).parent / "results.md",
        help="Markdown report path (default: tests/tck/results.md)",
    )
    args = p.parse_args(argv)
    oc9 = args.oc9_filter or os.environ.get("CYPHERAST_TCK_OC9_FILTER", "").lower() in {
        "1",
        "true",
        "yes",
    }

    board = run_official(
        parse_only=args.parse_only,
        oc9_filter=oc9,
        report_path=args.report,
        dialect=args.dialect,
    )
    print(board.summary())
    print(f"Report: {args.report}")
    failures = [r for r in board.results if not r.passed and r.kind != "skip"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
