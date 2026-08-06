---
applyTo: "**/*.py"
---

# Python review focus (cypherast)

- Prefer graph/Cypher naming in identifiers and user-facing strings.
- Public API changes must update `cypherast/__init__.py` exports and usually `docs/api.md` / `README.md`.
- Avoid circular imports: do not import `cypherast.optimizer` at the top of `cypherast/rewriter/__init__.py`.
- Dialect constraint callables should accept `(tree, schema=None)` so `RuleSet.apply` can pass kwargs.
- Tests: use `cypherast.parse_one` / `optimize` / `translate` / `validate`; assert via `.cypher(...)` when checking emit.
- Typecheck is strict (`mypy` on `cypherast` package) — new public functions need annotations.
