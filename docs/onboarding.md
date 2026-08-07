# Onboarding to the cypherast codebase

Short map for contributors and AI assistants. Canonical policy: root [`AGENTS.md`](../AGENTS.md) and [`.agents/rules/`](../.agents/rules/).

## Pipeline

```text
Cypher text
    → lexer / parser          (cypherast/lexer.py, parser.py)
    → AstNode IR              (cypherast/ast.py)
    → dialects                (capabilities, transforms/, validate/)
    → optimizer RuleSet       (cypherast/optimizer/* — IR passes + catalog)
    → planner / executor      (optional: explain, run)
    → Renderer                (AstNode.cypher / dialect renderer)
```

`rewriter/` is a back-compat shim that re-exports optimizer passes — prefer importing from `cypherast.optimizer`.

## Where to change what

| Goal | Start here |
|------|------------|
| New AST node / arg | `ast.py`, parser, renderer, tests |
| Parse edge case | `parser.py` + `tests/test_parse.py` |
| Shared IR rewrite | `optimizer/<pass>.py` + register in `optimizer/catalog.py` |
| Engine rewrite | `dialects/transforms/` + capability flag + `constraint_rules` |
| Engine reject | `dialects/validate/` + capability flag |
| Public API | `cypherast/__init__.py` + `docs/api.md` |
| In-memory exec | `executor/` |

## Dev loop

```bash
uv sync --group dev
make check          # ruff + mypy + pytest
make test-puppy     # PuppyGraph-focused tests
make optimize Q="MATCH (n:Person) RETURN n.name" WRITE=puppygraph
make validate Q="MATCH (n) RETURN n" DIALECT=puppygraph
```

Prefer a minimal Cypher string that reproduces the bug before large refactors.

## Design rules (short)

1. **Graph-native naming** — MATCH, pattern, binding, hop. No SQL vocabulary in public APIs/docs.
2. **One AST** — dialects converge on the same node types.
3. **Capabilities over hard-coding** — no customer-specific labels in dialect modules.
4. **Reject vs rewrite** — if a rewrite would emit still-broken Cypher, prefer validate/`strict` raise.
5. **`merge_match_chains` stays opt-in.**

## Common pitfalls

| Pitfall | Fix |
|---------|-----|
| Treating `find_all(NodePattern)` as “all MATCH binders” | Pattern predicates / comprehensions also contain nodes — use scope or clause walk |
| Inventing variables in WHERE path patterns | Engines reject new binders; keep anonymous `(:Label)` |
| Expecting LIMIT injection on PuppyGraph optimize | Removed in 0.1.2 — caller/engine owns LIMIT |
| Expecting hop-cap rejection in cypherast | Non-goal; query_guard / prevalid |
| `optimize` “just returns AST” for invalid dialect queries | Default `strict=True` raises `ValidationError` |
| Undeclared props failing without schema | Non-goal unless caller passes `GraphSchema` (and often `strict=True`) |

## Reading order

1. [ast_primer.md](ast_primer.md)
2. [optimizer.md](optimizer.md)
3. [dialects.md](dialects.md)
4. [api.md](api.md)
5. `AGENTS.md` + `.agents/rules/architecture.md`

## Tests

- Public API: `import cypherast` (`parse_one`, `optimize`, `translate`, `validate`)
- Assert emit with `.cypher(dialect=…)`
- Named rules: `tests/test_optimizer_rules.py`
- PuppyGraph: `tests/test_puppygraph_dialect.py`
- Schema catalog: `tests/test_schema_catalog.py`
