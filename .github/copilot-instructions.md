# GitHub Copilot — repository-wide instructions (chat, coding agent, code review)

## What this repo is

**cypherast** is a Cypher/GQL library (lexer → parser → AST → named rewrite rules → planner → in-memory executor).
Python 3.11+, zero runtime dependencies, MIT. Public API lives in `cypherast/__init__.py`.

This is a **graph query** toolchain. Use Cypher/GQL vocabulary (MATCH, pattern, binding, hop, dialect). Do not frame APIs or reviews in SQL terms.

For deeper agent context see root `AGENTS.md`. Prefer that file over inventing architecture.

## When reviewing a PR

Flag as blockers:

1. New runtime dependencies without clear justification
2. SQL-shaped public names (`sql()`, `transpile_sql`, etc.) or docs that describe the library as a SQL clone
3. Enabling `merge_match_chains` in default `RULES` (Cartesian risk on some engines)
4. Hard-coding customer-specific graph labels/rel types into dialect constraint code — use `DialectCapabilities` / generic rules
5. Qualifying anonymous variables inside pattern predicates (engines reject new bindings there)
6. Breaking `AstNode.cypher(...)` / `cypher=` public naming
7. Skipping tests for parser, rewriter, optimizer rule, or dialect capability changes
8. Lowering coverage gate or silencing CI (`|| true` on mypy/tests) without discussion
9. Re-adding LIMIT injection or hop-cap silent rewrite for PuppyGraph without an explicit product ask
10. Softening `optimize` default `strict=True` without documenting the API break

Nits (non-blocking unless pervasive):

- Missing type hints on new public functions
- Rewriter pass registered in the wrong order vs `optimizer/catalog.py`
- Docs/README not updated when public API changed

## Architecture map (for understanding diffs)

| Path | Owns |
|------|------|
| `cypherast/lexer.py`, `parser.py`, `ast.py` | Tokenize / parse / IR |
| `cypherast/dialects/` | Dialect registry, capabilities, constraint rewrites |
| `cypherast/rewriter/` | Individual AST rewrite passes |
| `cypherast/optimizer/` | Named `Rule` / `RuleSet`, catalogs, `only`/`disable` |
| `cypherast/planner/` | Explain / cost / plans |
| `cypherast/executor/` | In-memory `Graph` + execute |
| `cypherast/renderer.py` | AST → Cypher text |
| `tests/` | pytest; `tests/tck/` = sample parse-rate features only |

Pipeline order: parse → (optional) optimize/constraints → render / plan / run.

## Dialects & optimize

- Dialects: `opencypher`, `neo4j`, `memgraph`, `puppygraph`
- `optimize(..., write=)` applies canonicalizer rules then write-dialect constraints, then raises if `strict=True` (default)
- Filters: `only` / `disable` (canonicalizer), `constraint_only` / `constraint_disable`
- Default rules: `qualify` → `canonicalize_patterns` → `simplify` → `pushdown_predicates` → `annotate_types`
- Opt-in: `OPTIONAL_RULES` includes `merge_match_chains`
- PuppyGraph: labelled MATCH, FET-45 CASE guard, strip NULLS order; **no** LIMIT inject / hop-cap rewrite
- Schema catalog via `schema=`; `GraphSchema.strict` defaults False

## How to verify locally (tell authors)

```bash
uv sync --group dev
make check          # ruff + mypy + pytest
make test-cov       # coverage XML + term
make test-puppy     # PuppyGraph dialect tests
```

CI workflows:

- `.github/workflows/ci.yml` — ruff, mypy (strict), pytest with `--cov-fail-under=60`, uploads `coverage.xml`
- `.github/workflows/release.yml` — tag `v*` → verify version → build → PyPI (OIDC) → GitHub Release

## Coding conventions for suggestions

- Match existing style: ruff line-length 100, mypy strict, Python 3.13
- Prefer small, test-backed changes over large refactors
- New rewrite logic → implement under `rewriter/`, register name in `optimizer/catalog.py`
- New engine limits → `DialectCapabilities` + named constraint rule, not one-off string hacks
- Keep comments/docs free of SQL-toolchain brand names
