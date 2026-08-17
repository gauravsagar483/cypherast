# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Official openCypher TCK parse coverage now expands Scenario Outlines and scores all 3,897
  compiled scenarios. Compile-time-error scenarios accept parser rejection; positive and runtime
  scenarios must parse. Current parse rate is 100%.
- Parser support for hexadecimal and octal integer literals, bare patterns inside `EXISTS { … }`,
  parenthesized `SET (expr).property` targets, and detailed bidirectional relationship patterns.
- `allow_mixed_aggregate_projection` capability (off for PuppyGraph only): a projection item
  may not combine an aggregate with a bare reference, as in `RETURN n.age + count(*)`, matching
  PuppyGraph's `AggregationMixingCheck`. Validate reports `CG1401` with a hint to aggregate in
  an earlier `WITH` and combine the aliases afterwards. Arithmetic over aggregates alone
  (`count(*) + 1`) and standalone grouping keys beside aggregates stay valid. Left on for
  Neo4j / Memgraph / openCypher, which accept an exact standalone grouping key inside the
  aggregate expression.

## [0.1.10] - 2026-08-08

### Added

- Versioned Neo4j dialects: `neo4j25` (aliases `neo4j`, `neo`) for the Cypher 25
  surface and `neo4j5` (alias `cypher5`) pinned to pre–Cypher 25. Both descend from a
  shared `CypherDialect` / `CypherRenderer` base (`cypherast/dialects/cypher.py`) that
  `memgraph` and `opencypher` also inherit, so pattern-predicate style and unsupported
  node sets are declared per dialect instead of duplicated per renderer.
- Cypher 25 and Memgraph surface parse + render + validate, each behind a
  `DialectCapabilities` flag rather than a dialect-name check: `FILTER`, `FOR`, `LET`,
  `GROUP BY` subclause, `SEARCH`, `WHEN … THEN { … }`, `CALL (vars) { … }`,
  `OPTIONAL CALL`, `CALL … IN TRANSACTIONS OF n ROWS`, inline pattern `WHERE` (node and
  relationship), label expressions, `LOAD CSV`, admin DDL passthrough, and Memgraph
  `*bfs` / `*wShortest` relationship quantifiers. Unsupported surfaces report `CG1520`
  (needs Cypher 25) or `CG1401` / `CG1521` (not in this dialect). The words these clauses
  introduce (`LOAD`, `CSV`, `FROM`, `HEADERS`, `FIELDTERMINATOR`, `GROUP`, `OF`,
  `TRANSACTIONS`, `ROWS`, `SEARCH`, `VECTOR`, `SCORE`, `SHOW`, `CONSTRAINT`, `ASSERT`,
  `UNIQUE`) are matched contextually, so they stay usable as variables and property names.
- Rendering now refuses constructs the target dialect does not declare, raising
  `CompatibilityError` (`CG1401`) instead of emitting text the engine would reject —
  `FILTER`, `FOR`, `LET`, `GROUP BY`, `SEARCH`, `WHEN`, `LOAD CSV`, admin statements, and
  Memgraph relationship quantifiers are each gated by their capability flag.
- Admin DDL keeps its original source text verbatim (`CREATE INDEX ON :Person(name)`
  round-trips), and Memgraph weight lambdas parse into a `RelationshipLambda` node rather
  than captured token text, so `*wShortest (e, n | e.weight) total` round-trips.
- Neutral Cypher core lowering seam (`cypherast/dialects/lower.py`,
  `lower_to_core(tree, dialect=…)`): dialect parse → optional target optimize/render
  → lowering → dialect-neutral planner / in-memory executor / lineage. Lowering
  returns a copy, so source trees keep their surface nodes.
- `execute(tree, …, dialect=…)` names the source surface for AST entry, matching
  `read=` (`explain` / `profile` / `run`) and `from_` (`lineage`). Internal
  `cypherast.planner` entry points accept the same keyword-only `dialect=`.
- Lowered for in-memory use: inline pattern `WHERE` (hoisted onto the owning `MATCH`
  or pattern comprehension), `FOR` → `UNWIND`, `FILTER` → `WITH … WHERE`,
  `LET` → one `WITH *, item` per item (sequential scope, so a later item may
  reference an earlier one), Memgraph `*bfs` → ordinary variable-length hop.
- Parser nesting guard: `cypherast.parser.MAX_PARSE_DEPTH` (`1000`, CPython's default
  recursion limit; overridable via `Parser(source, max_depth=…)`) counted over statement,
  expression, and path-pattern nesting. Overflow — from the guard or from the interpreter
  stack, which trips first because one nesting level costs several frames — raises
  `ParseError` **CG1105** with the offending position instead of letting a bare
  `RecursionError` escape `parse()`.
- `AGGREGATE_FUNCTIONS` in `cypherast/schema.py` — one aggregate-name catalog shared
  by the executor, dialect aggregate validation, and core lowering.
- TCK dialect transpose matrix (`make test-tck-dialects`,
  `tests/tck/results-dialects.md`) with one shared gate for the CLI and pytest:
  per-target run-rate floors plus minimum executable count and maximum skip ratio,
  so mass capability skips fail even at a 100% run rate. Report gained a skip-ratio
  column.

### Changed

- `neo4j` (and `neo`) now resolve to the Cypher 25 surface (`neo4j25`); `cypher5` is an
  alias of `neo4j5` instead of `neo4j`. Pin `read=`/`write=` to `neo4j5` to keep the
  previous pre–Cypher 25 behaviour.
- Planning, profiling, and execution always lower to core, so the neutral-core
  guarantee is structural instead of depending on the caller passing `dialect=`
  (lowering already-core AST is idempotent).
- `GROUP BY` metadata is cleared only when the clause aggregates and its keys equal
  the clause's non-aggregate projections (comparing the underlying expression or its
  alias). Mismatched keys, or grouping with no aggregate projection, raise
  `ExecuteError` (`CG1702`) instead of being dropped, which would have silently
  changed aggregate results or row counts.
- `CALL … IN TRANSACTIONS` batching metadata is still cleared: in-memory execution
  is single-process and non-batched, so there are no transactional batch semantics.
- Rejected during lowering (`ExecuteError` `CG1702`, never silently ignored):
  inline `WHERE` on a variable-length relationship (the binding is a relationship
  list, not a scalar to hoist), inline `WHERE` inside `shortestPath` / quantified
  paths (the predicate belongs to search / repetition semantics), a `FILTER` item whose
  predicate does not reference its own binding (core `WITH * WHERE …` filters the whole
  row, so the item's scope would be lost), Memgraph `wShortest`, `SEARCH`, `LOAD CSV`,
  admin statements, `WHEN`.
- The TCK dialect matrix buckets a transpose as a capability skip by issue code rather
  than by dialect name, so a regression on any target stays a failure instead of hiding
  in the skip bucket. `CG1201` (unknown variable) and `CG1501` (rewrite failed) are
  deliberately not excused. Measured after the change: `neo4j5` / `neo4j25` / `memgraph`
  97% of 569 executable, `puppygraph` 59% of 483 executable with 86 skips.

### Fixed

- `lineage` no longer recurses forever on `WITH n AS n` or alias cycles; the walk
  stops on a repeated binding name and keeps the last useful expression.
- `lineage` resolves a binding to the nearest preceding `WITH` definition before the
  `RETURN`, so a later `WITH` shadows an earlier alias of the same name instead of
  the first definition winning.

## [0.1.9] - 2026-08-08

### Added

- openCypher 9 validation (CG1501–CG1512): excluded clauses, undirected patterns,
  variable-length binding, quantified paths, USING hints, function signatures,
  comparability checks (`cypherast/dialects/validate/opencypher/`).
- ``opencypher9`` dialect alias (same capabilities as ``opencypher``).
- Official [openCypher TCK](https://github.com/opencypher/openCypher/tree/master/tck)
  runner: clone to ``/tmp``, dialect-aware parse/run scoreboard
  (``make test-tck-official``, ``tests/tck/results.md``).
- Multidialect regression suite (``tests/test_dialect_regression.py``,
  ``make test-dialects``) — all engines + public API with explicit ``read``/``write``.
- Parser/AST: label predicates (``n:Label``), list slices ``[n..m]`` / ``[n..]``,
  pattern comprehensions, keyword-safe property/map keys.
- Executor procedure stub registry (``cypherast/executor/procedures.py``).
- ``CALL { … }`` **RETURN** aliases exported to outer scope for CG1201 (PuppyGraph).
- Residual ``:_Node`` (+ ``_n_K`` if anon) after ``ensure_labelled_nodes`` mine/infer.
- Web Cypher transpile fixtures: ``tests/fixtures/web_cypher_queries.py``.
- Consolidated OC9 tests: ``tests/test_opencypher.py``.

### Fixed

- ``cypherast.lineage`` no longer overwritten by the ``lineage`` submodule on first
  call (lazy import rebound the package attribute to the module).
- PuppyGraph: allow bound variable-length relationships (``-[r*1..n]->``) — exempt
  from OC9 CG1504 for engine queries that bind path segments.

### Changed

- Removed vendored TCK ``.feature`` files; conformance runs against external clone only.
- Removed ``modern_graph_schema()`` and PuppyGraph default-schema inject. Pass
  caller ``schema=`` for endpoint inference; omit → query mine only + ``:_Node``.
- TCK runner: skip outlines, procedure stubs, unparseable queries; improved compare.

## [0.1.8] - 2026-08-07

### Added

- Parse/render ``CALL ns.proc(args) [YIELD …] [WHERE …]`` (``CallProcedure``):
  PuppyGraph ``algo.*``, Neo4j ``db.*`` / ``dbms.*``, Memgraph MAGE-style names.
  ``CALL { … }`` subquery unchanged. YIELD fields (and ``AS`` aliases) are in-scope for
  CG1201, including ``optimize(..., write="puppygraph", strict=True)`` with map args
  (refs each arg, not the arg list). No in-memory executor for procedures yet.

### Changed

- ``Yield`` is openCypher-renderable (procedure CALL); removed from renderer
  unsupported sets (base + Memgraph).

## [0.1.7] - 2026-08-07

### Changed

- ``GraphSchema.strict=True`` is closed-world: unknown node labels → **CG1301**,
  unknown relationship types → **CG1302** (plus existing undeclared props → CG1303).
  Also checks ``REMOVE n:Label``. ``strict=False`` / ``schema=None`` keep open-world
  ignore for unknown names (PuppyGraph tutorial default stays non-strict).

## [0.1.6] - 2026-08-07

### Fixed

- PuppyGraph **ET-17**: `optimize`/`validate` reject incompatible `CASE` THEN/ELSE arms
  (collected list vs list literal / map / scalar; map vs scalar). Hint cites `[ET-17]`.
  Compatible: same list vars, list literals together, `null` with any arm (FET-45).
  Scalar↔scalar (e.g. string vs int) left alone — PuppyGraph accepts those without schema.
- Parse/render: `REMOVE n:Label` → `RemoveLabels` (no `(n:Label)` / EXISTS reparse);
  map projection `n{.name}` preserves the property selector dot.
- In-memory executor: OPTIONAL WHERE keeps outer row; NULL bindings not rebound by later MATCH;
  aggregates honor `DISTINCT`; `WITH count(…)`; `ORDER BY` pre-RETURN vars; `*0..n` 0-hop;
  `NULLS FIRST/LAST`; `Graph.create_node("label")` as a single label.

### Changed

- Layout: dialect rewrites → `dialects/transforms/`; reject-only checks → `dialects/validate/`;
  `dialects/constraints.py` is a thin re-export facade. Canonicalizer passes live under
  `optimizer/` (`rewriter/` shim remains). FET-45 risky fn set moved to
  `DialectCapabilities.optional_risky_functions` (PuppyGraph sets it).

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

- Bound reuse in OPTIONAL/MATCH: do not copy sibling/neighbor labels onto already-bound vars (e.g. `(cat:Catalog) … OPTIONAL MATCH (cat)-[:HAS_CHECK]->(chk:…)` no longer becomes `(cat:Check)`).
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

[0.1.10]: https://github.com/gauravsagar483/cypherast/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/gauravsagar483/cypherast/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/gauravsagar483/cypherast/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/gauravsagar483/cypherast/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/gauravsagar483/cypherast/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/gauravsagar483/cypherast/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/gauravsagar483/cypherast/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/gauravsagar483/cypherast/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/gauravsagar483/cypherast/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/gauravsagar483/cypherast/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/gauravsagar483/cypherast/releases/tag/v0.1.0
