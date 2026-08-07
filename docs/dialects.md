# Dialects and capabilities

cypherast speaks multiple Cypher dialects through one AST. Dialects plug in at parse, render, and **capability** boundaries.

## Registered dialects

| Name | Role |
|------|------|
| `opencypher` | Default baseline |
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
| Require labelled MATCH nodes | `ensure_labelled_nodes` + CG1402 (schema/mined endpoints; no neighbor-label invent) |
| Reject true Cartesians | Disjoint multi-path MATCH; adjacent consecutive MATCH with no shared vars |
| Allow connected multi-path | e.g. `MATCH (a), (a)-[:R]->(b)` |
| Reject APT-18 / TE-14 / DISTINCT+agg landmines | Reject, don’t greenwash |
| Strip `NULLS FIRST/LAST` | Rewrite |
| Guard OPTIONAL `id()`/`split`/… | FET-45 CASE rewrite; `id(var) IS NOT NULL` counts; OR does not |
| Reject mismatched CASE arms | ET-16/ET-17: list↔list-lit, list↔map, list↔scalar (`allow_mismatched_case_arms=False`) |
| Undefined vars | **CG1201** (`WITH *`, SET/DELETE/REMOVE, comprehension binders) |
| Default tutorial schema when `schema=` omitted | Labelling only (`strict=False`) |

**Non-goals for PuppyGraph in cypherast:**

- Injecting `LIMIT`
- Enforcing max hops / rejecting unbounded `*` (query_guard / prevalid)
- Domain property catalogs without caller `GraphSchema`
- Inventing endpoint labels by copying the neighbor when schema has no endpoints

## Pattern predicates

Neo4j-style path pattern expressions must not introduce **new** binders. PuppyGraph sets `pattern_predicate_introduces_bindings=False`:

```cypher
-- OK: reuse outer n, anonymous end
MATCH (n:Person) WHERE (n)-[:KNOWS]->(:Person) RETURN n

-- Rejected: new binder m inside WHERE pattern
MATCH (n:Person) WHERE (n)-[:KNOWS]->(m:Person) RETURN n
```

Do not invent `_n_*` qualifiers inside pattern predicates when `require_labelled_nodes` is on.

## Custom dialect sketch

1. Subclass `Dialect` (often `OpenCypher`).
2. Set `name`, `capabilities`, optional `renderer_cls`.
3. Register with `@register`.
4. Add constraint rules via capability flags + `constraint_rules`.
5. Cover with `tests/test_*_dialect.py`.

Next: [optimizer.md](optimizer.md) · [onboarding.md](onboarding.md) · [api.md](api.md)
