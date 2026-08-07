---
applyTo: ".github/workflows/**/*.yml,cypherast/dialects/**/*.py,cypherast/optimizer/**/*.py,cypherast/rewriter/**/*.py"
---

# High-risk paths — Copilot code review

When reviewing changes under dialects, optimizer, rewriter, or CI workflows:

## Dialects / constraints

- Confirm capability flags match rewrite behavior (`allow_cartesian_match_paths`, var-length bounds, FET-45 rewrite flags).
- Do not reintroduce default MATCH-chain merge, `exists()` emit, LIMIT injection, or hop-cap silent rewrite for PuppyGraph unless capabilities explicitly allow it and docs/tests are updated.
- Unbounded `*` var-length must remain allowed when `allow_unbounded_var_length=True` and `max_var_length_hops is None`.
- `optimize` default `strict=True` is intentional — do not flip without an API note.

## Optimizer / rewriter

- Rule names in `only`/`disable` must match catalog names exactly.
- Keep `merge_match_chains` in `OPTIONAL_RULES` only unless the PR deliberately changes that policy and updates docs/tests.

## CI

- Do not drop coverage fail-under without calling it out in the PR.
- Do not make mypy or pytest non-blocking again.
- Coverage runs in the CI `test` job and must still produce `coverage.xml` artifact on failure when possible.
