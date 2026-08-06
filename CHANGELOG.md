# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Dialects including openCypher and PuppyGraph capability constraints (LIMIT inject, Cartesian MATCH split, collect/DISTINCT caps).
- Named optimizer `Rule` / `RuleSet` with `only` / `disable` / constraint filters.

[0.1.1]: https://github.com/gauravsagar483/cypherast/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/gauravsagar483/cypherast/releases/tag/v0.1.0
