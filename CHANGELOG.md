# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.5] - 2026-08-07

### Removed

- Module attribute `cypherast.__version__` (drifted from `pyproject.toml`). Use `importlib.metadata.version("cypherast")` instead.

## [0.1.4] - 2026-08-07

### Fixed

- PuppyGraph labelled-node rewrite: avoid `_n_*` self-joins on anonymous ends; parse/render node label OR (`:a|b`); drop neighbor-label copy fallback (infer from schema/mined endpoints only).
- Cartesian detection: allow connected multi-path MATCH (shared vars); reject adjacent disjoint consecutive MATCH; `merge_match_chains` stitches into one path instead of comma multi-path.
- List concatenation: scan WHERE / UNWIND / SET; do not fold `null + [list]` away before validate.
- FET-45: treat `id(var) IS NOT NULL` as a null guard; disjunctive `IS NOT NULL OR …` does not count.
- Undefined variables (**CG1201**): `WITH *` preserves scope; WITH WHERE uses projected aliases only; pattern/list comprehension binders ignored; SET / DELETE / REMOVE checked.
- Schema **CG1305**: map-projection entries (`n{.id}` / `n{id}`) treated like `n.id`.

### Changed

- Undefined-variable issues use **CG1201** (was CG1401).
- Neighbour-label invent fallback removed — supply `GraphSchema` endpoints (or mine from the query) for unlabelled ends.

## [0.1.3] - 2026-08-07

### Fixed

- Bound reuse in OPTIONAL/MATCH: do not copy sibling/neighbor labels onto already-bound vars (e.g. `(dl:DataLakeTables) … OPTIONAL MATCH (dl)-[:HAS_DQ_CHECK]->(dq:…)` no longer becomes `(dl:DataQualityCheck)`).
- Release gate: ruff B023 in UNION branch collect; mypy annotations on constraint helpers.

## [0.1.2] - 2026-08-07

### Added

- `GraphSchema` catalog helpers: `id_field`, `add_id_field`, `add_rel_id_field`, property lookups.
- `optimize` / `validate` accept `schema=` for id-field misuse (**CG1305**) and, when `schema.strict=True`, undeclared props on known labels (**CG1303**).
- FET-45 constraint rewrite `guard_optional_scalar_use`: wrap OPTIONAL `id()` / `split` / … in `CASE WHEN var IS NULL THEN null ELSE … END`.
- Neighbor-label fallback in `ensure_labelled_nodes` when schema/mined endpoints cannot infer an end label.
- Scope checks for `ORDER BY` / `SKIP` / `LIMIT` on `WITH` and `RETURN` under `check_undefined_variables` (**CG1401**).

### Changed

- `optimize(..., strict=True)` by default: remaining dialect/schema issues raise `ValidationError`. Use `strict=False` for a soft rewritten AST.
- `translate(..., optimize=True)` validates by default (same raise behavior); plain transpile stays soft.
- PuppyGraph: reject (do not rewrite) multi-`collect(DISTINCT)`, Cartesian multi-path MATCH, and `DISTINCT` beside aggregates.
- PuppyGraph: hop caps / unbounded `*` left to query_guard / engine prevalid (not cypherast).
- `GraphSchema.strict` defaults to `False` — catalog property checks only when the caller opts in.
- `NULLS FIRST` / `NULLS LAST` parsed contextually in `ORDER BY` (not global reserved keywords).
- Removed `require_limit_on_row_return` / `ensure_row_limit` — optimize no longer injects `LIMIT`.

### Fixed

- `CREATE` / `MERGE` variables visible to later `RETURN` when undefined-variable checks are on.
- Pattern-predicate binders no longer false-positive as undefined; new binders inside WHERE path patterns are hard-rejected.
- List concatenation: `expr[i] + …` is not treated as list-concat; `a + b` detected when aliases are `collect`/list.
- FET-45 “already guarded” detection is local to a wrapping `CASE` or `WHERE … IS NOT NULL` (not whole-tree).

## [0.1.1] - 2026-08-06

### Added

- Positive WHERE pattern predicates: parse `(a)-[:R]->(b)` as `PatternPredicate` (same path as `NOT (…)`).
- PuppyGraph constraint rule `ensure_labelled_nodes`: fill missing MATCH node labels from `GraphSchema` rel endpoints (label OR `:a|b` when multi-type).
- `modern_graph_schema()` helper; PuppyGraph `optimize` uses it when `schema=` is omitted.
- CG1402 validation for unlabelled MATCH nodes (bound-variable reuse of labelled vars allowed).
- Corpus harness `scripts/puppygraph_optimizer_corpus.py` (~50 PuppyGraph-shaped queries).

### Changed

- Qualify with `require_labelled_nodes`: do not invent `_n_*` on bare unlabelled `()`.
- PuppyGraph validate softens bare `(var)` after a prior labelled bind (OPTIONAL MATCH / WITH / chain).

### Fixed

- Qualify vs labelled-node rule fight on anonymous endpoints for PuppyGraph.
- Corpus path: optimize + validate clean for unlabelled `()-[e:knows]->()` via schema labelling.

## [0.1.0] - 2026-08-06

### Added

- Initial public release of **cypherast** (Cypher/GQL parse, rewrite, optimize, plan, execute).
- Dialects including openCypher and PuppyGraph capability constraints (Cartesian MATCH handling, collect/DISTINCT caps).
- Named optimizer `Rule` / `RuleSet` with `only` / `disable` / constraint filters.

[0.1.5]: https://github.com/gauravsagar483/cypherast/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/gauravsagar483/cypherast/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/gauravsagar483/cypherast/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/gauravsagar483/cypherast/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/gauravsagar483/cypherast/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/gauravsagar483/cypherast/releases/tag/v0.1.0
