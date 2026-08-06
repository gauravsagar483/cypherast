# cypherglot — agent instructions

Cypher/GQL library: lexer → parser → AST → named rewrite rules → planner → in-memory executor.
Zero runtime deps. Python **3.13+**. Package version **0.1.0** (`pyproject.toml`). MIT.

Canonical AI instructions live here. Topic rules live under `.agents/rules/` only (no tool-specific stub/rule trees in-repo).

## Non-negotiables

- Graph-native naming only (MATCH, pattern, binding, hop). No SQL vocabulary in public APIs or docs.
- Never frame the library as a SQL toolchain clone — see `.agents/rules/graph-native-naming.md`.
- Prefer `AstNode.cypher(...)` for render; public params use `cypher=`, not SQL-shaped names.
- Do not add runtime dependencies without an explicit request.
- Do not invent dialect capability limits — read `DialectCapabilities` / `cypherglot/dialects/constraints.py`.
- Do not hard-code customer-specific graph labels/rel types into dialect code.
## Public API (`cypherglot/__init__.py`)

| Function | Role |
|----------|------|
| `parse` / `parse_one` | Cypher → AST (`read=` dialect) |
| `optimize` | Canonicalizer + optional write-dialect constraints (`only` / `disable` / `constraint_*`) |
| `translate` / `transpile` | Parse `from_` → render `to_`; `optimize=` applies target constraints |
| `validate` | List capability `ConstraintIssue`s for a dialect |
| `explain` / `profile` / `run` | Plan / profile / execute on in-memory `Graph` |
| `lineage` | Binding provenance |

CLI entry: `cypherglot.cli:main` (`uv run cypherglot …`).

## Dialects

Registered under `cypherglot/dialects/`: `opencypher`, `neo4j`, `memgraph`, `puppygraph`.
`Dialect.optimize` runs `cypherglot.optimizer` `RULES` then `constraint_rules(capabilities)`.
PuppyGraph caps are generic engine limits (LIMIT, no Cartesian multi-path MATCH, etc.) — keep dialect code free of domain-specific label/rel names.

## Optimizer rules

- Default `RULES`: `qualify` → `canonicalize_patterns` → `simplify` → `pushdown_predicates` → `annotate_types`
- Opt-in: `OPTIONAL_RULES` (`merge_match_chains`) — not default (Cartesian risk on some engines)
- Constraints built by `constraint_rules(caps)` — e.g. `ensure_row_limit`, `split_multi_path_match`

## Dev commands (verified in `Makefile` / `pyproject.toml`)

```bash
uv sync --group dev
make check          # ruff + mypy + pytest
make test
make test-puppy
make optimize Q="MATCH (n:Person) RETURN n.name" WRITE=puppygraph
make optimize Q="..." DISABLE=qualify CONSTRAINT_DISABLE=ensure_row_limit
```

CI:

- `.github/workflows/ci.yml` — ruff, mypy (strict), pytest + coverage (fail-under 60%, uploads `coverage.xml`)
- `.github/workflows/release.yml` — on `v*` tags: verify tag==version → check → `uv build` → `uv publish` (OIDC) → GitHub Release

Copilot: `.github/copilot-instructions.md` (+ `.github/instructions/*.instructions.md`).

## Project Structure

Single Python package (uv + hatchling):

```text
cypherglot/
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
├── cypherglot/
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
│   ├── dialects/             # Dialect + capabilities + constraints
│   ├── rewriter/             # rewrite pass implementations
│   ├── optimizer/            # Rule / RuleSet / RULES catalog
│   ├── planner/
│   └── executor/             # in-memory Graph + engine
└── tests/
    ├── test_*.py
    └── tck/                  # sample .feature parse-rate suite
```
