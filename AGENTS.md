# cypherast — agent instructions

Cypher/GQL library: lexer → parser → AST → named rewrite rules → planner → in-memory executor.
Zero runtime deps. Python **3.11+**. Package version **0.1.7** (`pyproject.toml`). MIT.

Canonical AI instructions live here. Topic rules live under `.agents/rules/` only (no tool-specific stub/rule trees in-repo).

## Non-negotiables

- Graph-native naming only (MATCH, pattern, binding, hop). No SQL vocabulary in public APIs or docs.
- Never frame the library as a SQL toolchain clone — see `.agents/rules/graph-native-naming.md`.
- Prefer `AstNode.cypher(...)` for render; public params use `cypher=`, not SQL-shaped names.
- Do not add runtime dependencies without an explicit request.
- Do not invent dialect capability limits — read `DialectCapabilities` / `cypherast/dialects/capabilities.py` (+ `transforms/` / `validate/`).
- Do not hard-code customer-specific graph labels/rel types into dialect code.
## Public API (`cypherast/__init__.py`)

| Function | Role |
|----------|------|
| `parse` / `parse_one` | Cypher → AST (`read=` dialect) |
| `optimize` | Canonicalizer + write-dialect constraints; **raises** on remaining issues by default (`strict=True`) |
| `translate` / `transpile` | Parse `from_` → render `to_`; `optimize=True` applies target constraints + validate |
| `validate` | List capability / schema `ConstraintIssue`s (`schema=` optional) |
| `explain` / `profile` / `run` | Plan / profile / execute on in-memory `Graph` |
| `lineage` | Binding provenance |

CLI entry: `cypherast.cli:main` (`uv run cypherast …`).

## Dialects

Registered under `cypherast/dialects/`: `opencypher`, `neo4j`, `memgraph`, `puppygraph`.
`Dialect.optimize` runs `cypherast.optimizer` `RULES` then `constraint_rules(capabilities)`, then raises if `strict` (default).
PuppyGraph caps are generic engine limits (labelled MATCH, no Cartesian multi-path MATCH, FET-45 CASE guard, etc.) — keep dialect code free of domain-specific label/rel names. Hop caps and missing `LIMIT` are non-goals (query_guard / caller).

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
