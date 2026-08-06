---
applyTo: "**/*.py"
---

# Python review focus (cypherglot)

- Prefer graph/Cypher naming in identifiers and user-facing strings.
- Public API changes must update `cypherglot/__init__.py` exports and usually `docs/api.md` / `README.md`.
- Avoid circular imports: do not import `cypherglot.optimizer` at the top of `cypherglot/rewriter/__init__.py`.
- Dialect constraint callables should accept `(tree, schema=None)` so `RuleSet.apply` can pass kwargs.
- Tests: use `cypherglot.parse_one` / `optimize` / `translate` / `validate`; assert via `.cypher(...)` when checking emit.
- Typecheck is strict (`mypy` on `cypherglot` package) — new public functions need annotations.
