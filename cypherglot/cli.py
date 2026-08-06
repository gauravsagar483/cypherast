"""Thin CLI for cypherglot."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cypherglot", description="Cypher/GQL toolkit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_parse = sub.add_parser("parse", help="Parse and print AST")
    p_parse.add_argument("query")
    p_parse.add_argument("-r", "--read", default="opencypher")

    p_tr = sub.add_parser("translate", help="Translate between dialects")
    p_tr.add_argument("query")
    p_tr.add_argument("-r", "--read", default="opencypher")
    p_tr.add_argument("-w", "--write", default="opencypher")
    p_tr.add_argument("--pretty", action="store_true")

    p_opt = sub.add_parser("optimize", help="Rewrite to canonical form")
    p_opt.add_argument("query")
    p_opt.add_argument("-r", "--read", default="opencypher")

    p_ex = sub.add_parser("explain", help="Show query plan")
    p_ex.add_argument("query")

    p_run = sub.add_parser("run", help="Execute against empty in-memory graph")
    p_run.add_argument("query")

    args = parser.parse_args(argv)
    import cypherglot

    if args.cmd == "parse":
        tree = cypherglot.parse_one(args.query, read=args.read)
        print(repr(tree))
        return 0
    if args.cmd == "translate":
        print(cypherglot.translate(args.query, from_=args.read, to_=args.write, pretty=args.pretty))
        return 0
    if args.cmd == "optimize":
        tree = cypherglot.optimize(args.query, read=args.read)
        print(tree.cypher(pretty=True))
        return 0
    if args.cmd == "explain":
        print(cypherglot.explain(args.query))
        return 0
    if args.cmd == "run":
        from cypherglot.executor import Graph

        result = cypherglot.run(args.query, graph=Graph())
        from cypherglot.executor.engine import Result

        print(list(result) if isinstance(result, Result) else result)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
