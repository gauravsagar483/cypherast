# Contributing to cypherast

## Setup

```bash
uv sync --group dev
make pre-commit-install   # git hook: ruff check + pytest on every commit
make check
```

Requires Python 3.11+ (`requires-python` in `pyproject.toml`).

### Pre-commit

Configured in `.pre-commit-config.yaml` (local hooks via `uv run`):

- `ruff check .`
- `pytest`

```bash
make pre-commit-install
make pre-commit-run          # run hooks without committing
# or: uv run pre-commit run --all-files
```

## Workflow

1. Keep changes scoped — match existing module boundaries (`dialects`, `rewriter`, `optimizer`, `planner`, `executor`).
2. Add or update tests under `tests/` for behavior changes.
3. Run `make check` (ruff, mypy, pytest) before opening a PR.
4. Prefer graph-native naming; see `AGENTS.md` and `.agents/rules/`.

## Code style

- Ruff: line length 100, target `py313` (`pyproject.toml`).
- Mypy: `strict = true` on the `cypherast` package.
- Zero runtime dependencies unless explicitly agreed.

## Tests

```bash
make test
make test-cov
make test-puppy
make test-tck
```

CI runs ruff, mypy (strict), and pytest with coverage (fail-under 60%) in one workflow.

## Release / PyPI

1. Bump `version` in `pyproject.toml`.
2. Tag `vX.Y.Z` matching that version and push the tag.
3. `.github/workflows/release.yml` builds, publishes via PyPI trusted publishing, opens a GitHub Release.

See README **Publishing to PyPI** for one-time publisher setup.

## Docs

Update `README.md` / `docs/api.md` when the public API changes. Keep AI instructions in `AGENTS.md` (not duplicated into tool stubs).
