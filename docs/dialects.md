# Dialects and capabilities

cypherast speaks multiple Cypher dialects through one AST. Dialects plug in at parse, render, and **capability** boundaries.

## Inheritance

```text
Dialect (registry machinery)
└── CypherDialect (permissive CypherRenderer)
    ├── Neo4jCypher5 (`neo4j5`, alias `cypher5`)
    │   ├── Neo4jCypher25 (`neo4j25`, aliases `neo4j`, `neo`)
    │   └── Memgraph (`memgraph`, alias `mg`)
    └── OpenCypher (`opencypher`, OC9 caps)
        └── PuppyGraph (engine constraints)
```

## Registered dialects

| Name | Aliases | Role |
|------|---------|------|
| `opencypher` | `cypher`, `oc`, … | openCypher 9 baseline (validation + bare pattern predicates) |
| `opencypher9` | `oc9`, … | Alias for `opencypher` |
| `neo4j25` | `neo4j`, `neo` | Latest Neo4j / Cypher 25 surface |
| `neo4j5` | `cypher5` | Pinned Cypher 5 (pre–Cypher 25 clauses) |
| `memgraph` | `mg` | Memgraph classic Cypher + MAGE procedures |
| `puppygraph` | `puppy` | openCypher subclass + engine capability constraints |

```python
import cypherast

cypherast.parse_one(q, read="puppygraph")
cypherast.optimize(q, write="puppygraph")
cypherast.translate(q, from_="opencypher", to_="puppygraph", optimize=True)
cypherast.validate(q, dialect="puppygraph")
```

List names: `cypherast.dialect_names()`.

## Neutral Cypher core

Semantic APIs share one pipeline:

```text
dialect parse (read= / from_ / dialect=)
  → optional target optimize / render (write / to_)
  → lower_to_core(…, dialect=<source surface>)
  → neutral Cypher core
  → planner / in-memory executor / lineage
```

`explain` / `profile` / `run` use `read=`; `lineage` uses `from_=` (text or AST); AST `execute` uses `dialect=`. All name the **source** surface that produced the tree. Internals after lowering are dialect-neutral by design — capability details are stripped at the seam, not interpreted inside the engine.

`lower_to_core` returns a copy (source AST unchanged). Lowering is structural, so planner and executor lower even without a named dialect; the keyword identifies the surface, it does not switch the guarantee on. Unsupported semantic surfaces are never silently ignored — they raise `ExecuteError` (`CG1702`).

| Surface | In-memory after lowering |
|---------|--------------------------|
| Inline pattern `WHERE` | Hoisted onto owning `MATCH` / comprehension |
| `FOR` / `FILTER` | `UNWIND` / `WITH … WHERE` |
| `LET a = …, b = …` | One `WITH *, item` per item (sequential scope: `b` may use `a`) |
| `GROUP BY` metadata | Cleared **only** when the clause aggregates and the keys equal its non-aggregate projections (alias or underlying expression) |
| `GROUP BY` keys differing from those projections, or `GROUP BY` with no aggregate | **Reject** (`CG1702`) — clearing them would change aggregate results or row counts |
| `FILTER` item whose predicate ignores its own binding | **Reject** (`CG1702`) — `WITH * WHERE …` filters the whole row, losing the item's scope |
| `CALL … IN TRANSACTIONS` batching metadata | Cleared (in-memory is single-process / non-batched; no transactional batch semantics) |
| Memgraph `*bfs` | Ordinary variable-length hop |
| Inline `WHERE` on a variable-length relationship | **Reject** (`CG1702`) — the binding is a relationship list, not a scalar |
| Inline `WHERE` inside `shortestPath` / quantified path | **Reject** (`CG1702`) — predicate belongs to search / repetition semantics |
| Memgraph `*wShortest` | **Reject** (`CG1702`) |
| `SEARCH` / `LOAD CSV` / admin statements / `WHEN` | **Reject** (`CG1702`) |

This documents in-memory executor support only — not live Neo4j / Memgraph / PuppyGraph parity. Dialects may still parse and render richer surfaces for transpile/optimize toward those engines.

## Capability flags

`DialectCapabilities` (`cypherast/dialects/capabilities.py`) describes what a target engine accepts. Examples:

- `require_labelled_nodes`
- `allow_cartesian_match_paths` / `rewrite_cartesian_match_paths`
- `allow_list_concat`, `allow_list_ops_on_aggregates`, `allow_distinct_with_aggregate`, …
- `allowed_functions`, `unsupported_functions`, `function_arity_overrides`
- `allow_map_projection`, `allow_exists_subquery`, `allow_count_subquery`
- `allow_write_clauses`, `allow_parameters`, `allow_multi_label_nodes`
- `rewrite_unguarded_optional_scalar_use` (FET-45 CASE rewrite)
- `optional_risky_functions` (which calls FET-45 guards — PuppyGraph sets id/split/…)
- `allow_mismatched_case_arms` (ET-16/ET-17)
- `check_undefined_variables`, `pattern_predicate_introduces_bindings`

**Rule:** engine limits go in capabilities + named constraint rules — transforms rewrite, validate rejects. Do not hard-code customer labels/rel types in dialect code.

## PuppyGraph (read-only target dialect)

PuppyGraph subclasses openCypher. On `optimize` / `validate` it typically:

| Behavior | Notes |
|----------|--------|
| Allow bare / unlabelled MATCH | Never invent `:_Node`; preserves result cardinality |
| Allow Cartesian and connected multi-path | Verified against the live engine |
| Reject unbounded variable-length patterns | Use an explicit upper bound; no cypherast maximum for bounded forms |
| Reject writes and admin clauses | PuppyGraph graph projection is read-only |
| Allow inline list comprehensions / list concat | Reject the same over a `collect()` result (ET-06 / ET-09); reject pattern comprehensions and map projections |
| Allow `CALL { … }` and `exists(prop)` | Reject `EXISTS { … }` and `COUNT { … }` expressions |
| Reject APT-18 / TE-14 / DISTINCT+agg landmines | Reject, don’t greenwash |
| Strip `NULLS FIRST/LAST` | Rewrite |
| Guard OPTIONAL `id()`/`split`/… | FET-45 CASE rewrite; `id(var) IS NOT NULL` counts; OR does not |
| Reject mismatched CASE arms | ET-16/ET-17: list↔list-lit, list↔map, list↔scalar (`allow_mismatched_case_arms=False`) |
| Undefined vars | **CG1201** (`WITH *`, quantifier/comprehension binders, `CALL { }` RETURN exports) |
| Function policy | Capability allow/deny sets plus PuppyGraph arity overrides |

**Non-goals for PuppyGraph in cypherast:**

- Injecting `LIMIT`
- Enforcing a maximum for explicitly bounded hops (query_guard / prevalid)
- Domain property catalogs / tutorial `person`/`software` inject without caller `GraphSchema`
- Inventing endpoint labels by copying the neighbor when schema has no endpoints
- Running graph algorithms inside `optimize` / in-memory `run` (parse+render only; execute on PuppyGraph)

## Procedure `CALL` (shared)

`CallProcedure` is dialect-shared openCypher surface (Neo4j `db.*` / `dbms.*`, Memgraph MAGE,
PuppyGraph `algo.*`). Same grammar:

```cypher
CALL module.procedure(arg, …) YIELD field [AS alias], … [WHERE …]
```

PuppyGraph examples: `algo.paral.pagerank`, `algo.wcc`, `algo.labelPropagation`. Consumer path:
parse/optimize → `.cypher()` → engine. No procedure-name catalog in capabilities (YAGNI for now).

## Pattern predicates

Neo4j-style path pattern expressions must not introduce **new** binders. PuppyGraph sets `pattern_predicate_introduces_bindings=False`:

```cypher
-- OK: reuse outer n, anonymous end
MATCH (n:Person) WHERE (n)-[:KNOWS]->(:Person) RETURN n

-- Rejected: new binder m inside WHERE pattern
MATCH (n:Person) WHERE (n)-[:KNOWS]->(m:Person) RETURN n
```

Do not invent labels in PuppyGraph patterns. The shared qualifier may name
anonymous nodes, but must not add `:_Node`.

## openCypher 9

`opencypher` uses `OPENCYPHER9_CAPABILITIES` — undefined-variable checks, excluded-clause rejection (**CG1501**–**CG1511**), function catalog validation, and bare pattern-predicate rendering. `opencypher9` is an alias.

```python
import cypherast

cypherast.validate(q, dialect="opencypher")
cypherast.optimize(q, write="opencypher")
```

PuppyGraph subclasses openCypher and extends the same OC9 base via
`dataclasses.replace` with live-engine-verified read constraints. Unlike strict
OC9 validation, PuppyGraph allows undirected patterns, `CALL { … }`,
`exists(prop)`, and binding a variable to a bounded variable-length
relationship (`-[r*1..n]->`).

Spec reference: [openCypher 9 (PDF)](https://s3.amazonaws.com/artifacts.opencypher.org/openCypher9.pdf).

Conformance is measured against the official [openCypher TCK](https://github.com/opencypher/openCypher/tree/master/tck) (cloned to `/tmp` at test time — see `make test-tck-official`). Latest scoreboard: `tests/tck/results.md`.

Dialect transpose: scenarios that **pass** on `opencypher` are `translate`d with `optimize=True` to `neo4j5`, `neo4j25`, `memgraph`, and `puppygraph`, then re-executed on the same in-memory graph setup (`make test-tck-dialects` → `tests/tck/results-dialects.md`). PuppyGraph capability residuals are recorded as skips (not failures); the rate gate uses the executable subset only.

## Custom dialect sketch

1. Subclass `Dialect` (often `OpenCypher`).
2. Set `name`, `capabilities`, optional `renderer_cls`.
3. Register with `@register`.
4. Add constraint rules via capability flags + `constraint_rules`.
5. Cover with `tests/test_*_dialect.py`.

Next: [optimizer.md](optimizer.md) · [onboarding.md](onboarding.md) · [api.md](api.md)
