---
description: Pytest conventions for cypherast
globs: tests/**/*.py
alwaysApply: false
---

# Testing

- Framework: **pytest** (`tests/`, `testpaths` in `pyproject.toml`).
- Name files `tests/test_*.py`. Prefer focused cases over giant fixtures.
- Public API tests go through `import cypherast` (`parse_one`, `optimize`, `translate`, `validate`).
- Dialect capability tests: `tests/test_puppygraph_dialect.py`.
- Named rule filters: `tests/test_optimizer_rules.py`.
- Parser/hardening: `tests/test_parse.py`, `tests/test_hardening.py`.
- TCK parse-rate: `tests/tck/` via `make test-tck` — do not treat sample `.feature` files as a full openCypher TCK.

## Rules

- Assert on rendered Cypher (`.cypher(...)`) or structured AST — not private rewriter helpers unless unit-testing that helper.
- When testing `only`/`disable`/`constraint_disable`, name the rule exactly as in `RULES.names` / `constraint_rule_set().names`.
- After dialect constraint changes, keep `make test-puppy` green.
- No network / live graph engines in unit tests — use in-memory `Graph` or AST-only checks.
