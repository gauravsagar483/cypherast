# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.2]: https://github.com/gauravsagar483/cypherast/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/gauravsagar483/cypherast/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/gauravsagar483/cypherast/releases/tag/v0.1.0
