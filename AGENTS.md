# cypherast — agent instructions

Cypher/GQL library: dialect parse → optional target optimize/render → source-dialect `lower_to_core` → neutral Cypher core → planner / in-memory executor / lineage.
Zero runtime deps. Python **3.11+**. Package version **0.1.10** (`pyproject.toml`). MIT.

Canonical AI instructions live here. Topic rules live under `.agents/rules/` only (no tool-specific stub/rule trees in-repo).

## Non-negotiables

- Graph-native naming only (MATCH, pattern, binding, hop). No SQL vocabulary in public APIs or docs.
- Never frame the library as a SQL toolchain clone — see `.agents/rules/graph-native-naming.md`.
- Prefer `AstNode.cypher(...)` for render; public params use `cypher=`, not SQL-shaped names.
- Do not add runtime dependencies without an explicit request.
- Do not invent dialect capability limits — read `DialectCapabilities` / `cypherast/dialects/capabilities.py` (+ `transforms/` / `validate/`).
- Do not hard-code customer-specific graph labels/rel types into dialect code.
- Never silently ignore unsupported dialect semantics for in-memory execution — raise `ExecuteError` (`CG1702`).

## Public API (`cypherast/__init__.py`)

| Function | Role |
|----------|------|
| `parse` / `parse_one` | Cypher → AST (`read=` dialect); includes `CALL {…}` and `CALL ns.proc(…) [YIELD …]` |
| `optimize` | Canonicalizer + write-dialect constraints; **raises** on remaining issues by default (`strict=True`) |
| `translate` / `transpile` | Parse `from_` → render `to_`; `optimize=True` applies target constraints + validate |
| `validate` | List capability / schema `ConstraintIssue`s (`schema=` optional) |
| `explain` / `profile` / `run` | Plan / profile / execute on in-memory `Graph` (`read=` source surface) |
| `lineage` | Binding provenance (`from_=` source surface) |

AST-level `execute(tree, …, dialect=…)` names the source surface the same way. Planner, executor, and lineage stay dialect-neutral internally: surfaces lower before those interfaces.

CLI entry: `cypherast.cli:main` (`uv run cypherast …`).

## Dialects

Registered under `cypherast/dialects/`: `opencypher`, `neo4j25` (`neo4j`/`neo`), `neo4j5` (`cypher5`), `memgraph`, `puppygraph`.
`Dialect.optimize` runs `cypherast.optimizer` `RULES` then `constraint_rules(capabilities)`, then raises if `strict` (default).
Renderer `unsupported` sets are built by `build_unsupported(capabilities, …)` in `dialects/cypher.py` — gate a construct by adding it to `CAPABILITY_GATED_NODES`, not by hand-listing nodes per renderer. Clause words Neo4j does not reserve (`LOAD`, `GROUP`, `ROWS`, `SEARCH`, `SHOW`, …) stay `IDENT` and are matched with the parser's `_check_word` / `_expect_word` helpers; adding them to `KEYWORDS` would break their use as variables.
PuppyGraph caps are generic engine limits (labelled MATCH, no Cartesian multi-path MATCH, FET-45 CASE guard, etc.) — keep dialect code free of domain-specific label/rel names. Hop caps and missing `LIMIT` are non-goals (query_guard / caller). Graph algorithms (`algo.*`) = parse/render `CallProcedure` then run on the engine; not optimizer rewrites.

### Neutral Cypher core (`dialects/lower.py`)

Semantic path: parse with the requested dialect → optional optimize/render for a *write* target → `lower_to_core(tree, dialect=…)` → core AST for planner / executor / lineage. Lowering returns a copy; source trees are unchanged. `dialect=` only names the source surface — lowering is structural and always runs (planner and executor lower even when `dialect=None`), so the neutral-core guarantee is not a caller convention.

Currently lowered for in-memory use: inline pattern `WHERE`, `FILTER` / `FOR`, `LET` (one `WITH` per item so later items can reference earlier ones), semantically redundant `GROUP BY` metadata on `RETURN`/`WITH`, Memgraph `*bfs`. `CALL … IN TRANSACTIONS` batching metadata is cleared because in-memory execution is single-process/non-batched (no transactional batch semantics). Explicitly unsupported (raise `ExecuteError` `CG1702`, never silently ignored): `GROUP BY` keys that differ from the clause's non-aggregate projections (or grouping with no aggregate), inline `WHERE` on a variable-length relationship, inline `WHERE` inside `shortestPath` / quantified paths, a `FILTER` item whose predicate does not reference its own binding, `wShortest`, `SEARCH`, `LOAD CSV`, admin statements, `WHEN`. This is not live-engine parity — only what the in-memory executor can consume after lowering.

Aggregate-name catalog lives once in `cypherast/schema.py` (`AGGREGATE_FUNCTIONS`) — reuse it, do not add another function list.

## Optimizer rules

- Default `RULES`: `qualify` → `canonicalize_patterns` → `simplify` → `pushdown_predicates` → `annotate_types`
- Opt-in: `OPTIONAL_RULES` (`merge_match_chains`) — not default (Cartesian risk on some engines)
- Constraints built by `constraint_rules(caps)` — e.g. `ensure_labelled_nodes`, `guard_optional_scalar_use`

## Dev commands (verified in `Makefile` / `pyproject.toml`)

```bash
uv sync --group dev
make pre-commit-install   # git hook: ruff + pytest on commit
make check          # ruff + mypy + pytest
make test
make test-puppy
make optimize Q="MATCH (n:Person) RETURN n.name" WRITE=puppygraph
make optimize Q="..." DISABLE=qualify CONSTRAINT_DISABLE=strip_nulls_order_modifiers
```

CI:

- `.github/workflows/ci.yml` — ruff, mypy (strict), pytest + coverage (fail-under 60%, uploads `coverage.xml`)
- `.github/workflows/release.yml` — on `v*` tags: verify tag==version → check → `uv build` → `uv publish` (OIDC) → GitHub Release

Copilot: `.github/copilot-instructions.md` (+ `.github/instructions/*.instructions.md`).

## Project Structure

Single Python package (uv + hatchling):

```text
cypherast/
├── AGENTS.md                 # this file (canonical AI instructions)
├── HOWTOAI.md
├── CONTRIBUTING.md
├── README.md
├── Makefile
├── pyproject.toml
├── LICENSE
├── .agents/rules/            # agent topic rules (canonical)
│   ├── graph-native-naming.md
│   ├── architecture.md
│   └── testing.md
├── .github/
│   ├── copilot-instructions.md
│   ├── instructions/         # path-scoped Copilot review rules
│   └── workflows/
│       ├── ci.yml            # lint + mypy + pytest/coverage
│       └── release.yml       # tag v* → PyPI + GitHub Release
├── docs/api.md
├── cypherast/
│   ├── __init__.py           # public API
│   ├── ast.py
│   ├── lexer.py
│   ├── parser.py
│   ├── renderer.py
│   ├── cli.py
│   ├── errors.py
│   ├── schema.py
│   ├── scope.py
│   ├── lineage.py
│   ├── dialects/             # Dialect + capabilities + transforms/ + validate/
│   ├── rewriter/             # back-compat shim → optimizer passes
│   ├── optimizer/            # Rule / RuleSet / RULES + IR passes
│   ├── planner/
│   └── executor/             # in-memory Graph + engine
└── tests/
    ├── test_*.py
    └── tck/                  # sample .feature parse-rate suite
```
