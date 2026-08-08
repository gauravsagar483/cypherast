# Dialects and capabilities

cypherast speaks multiple Cypher dialects through one AST. Dialects plug in at parse, render, and **capability** boundaries.

## Registered dialects

| Name | Role |
|------|------|
| `opencypher` | openCypher 9 baseline (validation + render) |
| `opencypher9` | Alias for `opencypher` |
| `neo4j` | Neo4j-oriented parse/render deltas |
| `memgraph` | Memgraph-oriented deltas |
| `puppygraph` | openCypher subclass + engine capability constraints |

```python
import cypherast

cypherast.parse_one(q, read="puppygraph")
cypherast.optimize(q, write="puppygraph")
cypherast.translate(q, from_="opencypher", to_="puppygraph", optimize=True)
cypherast.validate(q, dialect="puppygraph")
```

List names: `cypherast.dialect_names()`.

## Capability flags

`DialectCapabilities` (`cypherast/dialects/capabilities.py`) describes what a target engine accepts. Examples:

- `require_labelled_nodes`
- `allow_cartesian_match_paths` / `rewrite_cartesian_match_paths`
- `allow_list_concat`, `allow_distinct_with_aggregate`, …
- `rewrite_unguarded_optional_scalar_use` (FET-45 CASE rewrite)
- `optional_risky_functions` (which calls FET-45 guards — PuppyGraph sets id/split/…)
- `allow_mismatched_case_arms` (ET-16/ET-17)
- `check_undefined_variables`, `pattern_predicate_introduces_bindings`

**Rule:** engine limits go in capabilities + named constraint rules — transforms rewrite, validate rejects. Do not hard-code customer labels/rel types in dialect code.

## PuppyGraph (write dialect)

PuppyGraph subclasses openCypher. On `optimize` / `validate` it typically:

| Behavior | Notes |
|----------|--------|
| Require labelled MATCH nodes | `ensure_labelled_nodes`: mine/infer from query + caller `schema=`; residual `:_Node` |
| Reject true Cartesians | Disjoint multi-path MATCH; adjacent consecutive MATCH with no shared vars |
| Allow connected multi-path | e.g. `MATCH (a), (a)-[:R]->(b)` |
| Reject APT-18 / TE-14 / DISTINCT+agg landmines | Reject, don’t greenwash |
| Strip `NULLS FIRST/LAST` | Rewrite |
| Guard OPTIONAL `id()`/`split`/… | FET-45 CASE rewrite; `id(var) IS NOT NULL` counts; OR does not |
| Reject mismatched CASE arms | ET-16/ET-17: list↔list-lit, list↔map, list↔scalar (`allow_mismatched_case_arms=False`) |
| Undefined vars | **CG1201** (`WITH *`, SET/DELETE/REMOVE, comprehension binders, `CALL { }` RETURN exports) |
| No default domain schema | Pass caller `GraphSchema` for endpoint inference; omit → query mine + `:_Node` residual |

**Non-goals for PuppyGraph in cypherast:**

- Injecting `LIMIT`
- Enforcing max hops / rejecting unbounded `*` (query_guard / prevalid)
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

Do not invent `_n_*` qualifiers inside pattern predicates when `require_labelled_nodes` is on.

## openCypher 9

`opencypher` uses `OPENCYPHER9_CAPABILITIES` — undefined-variable checks, excluded-clause rejection (**CG1501**–**CG1511**), function catalog validation, and bare pattern-predicate rendering. `opencypher9` is an alias.

```python
import cypherast

cypherast.validate(q, dialect="opencypher")
cypherast.optimize(q, write="opencypher")
```

PuppyGraph subclasses openCypher and extends the same OC9 base via `dataclasses.replace` with engine-specific constraints (labelled nodes, Cartesian rejection, FET-45, etc.). Unlike strict OC9 validate, PuppyGraph **allows** binding a variable to a variable-length relationship (`-[r*1..n]->`); use anonymous or path variables only when targeting `opencypher` / `opencypher9`.

Spec reference: [openCypher 9 (PDF)](https://s3.amazonaws.com/artifacts.opencypher.org/openCypher9.pdf).

Conformance is measured against the official [openCypher TCK](https://github.com/opencypher/openCypher/tree/master/tck) (cloned to `/tmp` at test time — see `make test-tck-official`). Latest scoreboard: `tests/tck/results.md`.

## Custom dialect sketch

1. Subclass `Dialect` (often `OpenCypher`).
2. Set `name`, `capabilities`, optional `renderer_cls`.
3. Register with `@register`.
4. Add constraint rules via capability flags + `constraint_rules`.
5. Cover with `tests/test_*_dialect.py`.

Next: [optimizer.md](optimizer.md) · [onboarding.md](onboarding.md) · [api.md](api.md)
