---
applyTo: ".github/workflows/**/*.yml,cypherglot/dialects/**/*.py,cypherglot/optimizer/**/*.py,cypherglot/rewriter/**/*.py"
---

# High-risk paths — Copilot code review

When reviewing changes under dialects, optimizer, rewriter, or CI workflows:

## Dialects / constraints

- Confirm capability flags match rewrite behavior (`require_limit_on_row_return`, `allow_cartesian_match_paths`, var-length bounds).
- Do not reintroduce default MATCH-chain merge or `exists()` emit for PuppyGraph unless capabilities explicitly allow it.
- Unbounded `*` var-length must remain allowed when `allow_unbounded_var_length=True` and `max_var_length_hops is None`.

## Optimizer / rewriter

- Rule names in `only`/`disable` must match catalog names exactly.
- Keep `merge_match_chains` in `OPTIONAL_RULES` only unless the PR deliberately changes that policy and updates docs/tests.

## CI

- Do not drop coverage fail-under without calling it out in the PR.
- Do not make mypy or pytest non-blocking again.
- Coverage runs in the CI `test` job and must still produce `coverage.xml` artifact on failure when possible.
