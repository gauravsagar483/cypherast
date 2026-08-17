# cypherast

Cypher/GQL transpiler, rewriter, cost-based planner, and in-memory executor.

Zero runtime dependencies. Python 3.11+. Graph-native API — no SQL vocabulary.

## Install

```bash
# from source (dev)
uv sync --group dev

# from PyPI (after a release tag)
uv add cypherast
# or: uv pip install cypherast
```

## Quick start

```python
import cypherast

q = "MATCH (n:Person) WHERE n.age > 30 RETURN n.name"
tree = cypherast.parse_one(q)
print(tree.cypher(pretty=True))

print(cypherast.optimize(q).cypher(pretty=True))

print(cypherast.translate(q, from_="opencypher", to_="neo4j", pretty=True))
# alias:
print(cypherast.transpile(q, from_="opencypher", to_="memgraph"))
```

## Public API

| Function | Purpose |
|----------|---------|
| `parse` / `parse_one` | Cypher text → AST |
| `translate` / `transpile` | Cross-dialect rewrite |
| `optimize` | Canonicalizer rewriter passes |
| `explain` / `profile` | Cost / naive plan text (`read=` source dialect) |
| `run` | Execute on in-memory `Graph` (`read=` source dialect) |
| `lineage` | Binding-level provenance (`from_=` source dialect) |

Full samples: [docs/api.md](docs/api.md). Guides: [docs/](docs/README.md) (AST primer, optimizer, dialects, onboarding).

### parse / parse_one

```python
tree = cypherast.parse_one(
    "MATCH (a:Person)-[:KNOWS]->(b) RETURN a.name, b.name",
    read="opencypher",  # or neo4j / memgraph / puppygraph
)
print(tree.cypher())

# Procedure CALL (openCypher / Neo4j / Memgraph / PuppyGraph algo.*)
# Distinct from CALL { subquery }. YIELD bindings are in-scope for optimize/validate.
proc = cypherast.parse_one(
    "CALL algo.wcc({labels: ['User'], relationshipTypes: ['LINK']}) "
    "YIELD id, componentId RETURN id, componentId"
)
print(proc.cypher())
```

### translate (transpile)

```python
out = cypherast.translate(
    "MATCH (n:Person) RETURN n",
    from_="opencypher",
    to_="neo4j",
    pretty=True,
)
print(out)
```

### optimize

Folds `WHERE n.x = lit` into `(n {x: lit})`, simplifies expressions, then applies write-dialect
constraints. By default **`strict=True`**: leftover dialect/schema issues raise `ValidationError`
(same codes as `validate`). Pass `strict=False` for a soft rewritten AST.

Rules are named and toggleable:

```python
from cypherast.optimizer import RULES, OPTIONAL_RULES
from cypherast.schema import GraphSchema

print(
    cypherast.optimize(
        "MATCH (n:Person) WHERE n.status = 'ACTIVE' RETURN n"
    ).cypher(pretty=True)
)
# MATCH (n:Person {status: 'ACTIVE'}) RETURN n

# disable / only
cypherast.optimize(q, disable=["qualify", "annotate_types"])
cypherast.optimize(q, write="puppygraph", constraint_disable=["strip_nulls_order_modifiers"])
cypherast.optimize(q, rules=RULES + OPTIONAL_RULES)  # opt-in merge_match_chains

# optional graph catalog (id fields; labels/rels/props when schema.strict=True)
schema = GraphSchema()
schema.add_label("Person", name="string")
schema.add_id_field("DataQualityCheck", "dq_check_id")
cypherast.optimize(q, write="puppygraph", schema=schema)
```

### explain / profile / run

Public text APIs take `read=` for the source dialect. Before plan / profile / execute, cypherast lowers the surface AST to a **neutral Cypher core** (`lower_to_core`). Planner and executor stay dialect-blind after that seam. Unsupported semantic surfaces raise `ExecuteError` (`CG1702`) — they are never silently ignored.

```python
from cypherast.executor import Graph, execute

print(cypherast.explain(
    "MATCH (n:Person)-[:KNOWS]->(m) RETURN n, m",
    read="opencypher",
))

g = Graph()
g.create_node(["Person"], {"name": "Ada", "age": 36})
rows = cypherast.run(
    "MATCH (n:Person WHERE n.age > 30) RETURN n.name",
    graph=g,
    read="neo4j25",
)
print(list(rows))

# AST entry: dialect= names the same source surface
tree = cypherast.parse_one("FOR n IN [1, 2] RETURN n", read="neo4j25")
print(list(execute(tree, dialect="neo4j25")))
```

Lowered today: inline pattern `WHERE`, `FILTER` / `FOR`, `LET` (one `WITH` per item, so a later item may reference an earlier one), redundant `GROUP BY` metadata, Memgraph `*bfs`; `CALL … IN TRANSACTIONS` batching metadata is cleared (in-memory is single-process/non-batched — no transactional batch semantics). Not executable in-memory (`CG1702`): `GROUP BY` keys that differ from the clause's non-aggregate projections (or grouping with no aggregate), inline `WHERE` on a variable-length relationship, inline `WHERE` inside `shortestPath` / quantified paths, `wShortest`, `SEARCH`, `LOAD CSV`, admin statements, `WHEN`. Parse/optimize/translate toward a live engine is separate from in-memory `run`.

### lineage

```python
root = cypherast.lineage(
    "MATCH (n:Person) LET age = n.age RETURN age",
    binding="age",
    from_="neo4j25",
)
print(root)  # provenance Node; .to_html() for vis.js
```

Bindings resolve backwards from `RETURN`, so a later `WITH` shadows an earlier alias of the same name; repeated names stop the walk (`WITH n AS n` and alias cycles terminate).

## CLI

```bash
uv run cypherast parse "MATCH (n) RETURN n"
uv run cypherast translate "MATCH (n) RETURN n" -r opencypher -w neo4j --pretty
uv run cypherast optimize "MATCH (n:Person) WHERE n.x = 1 RETURN n"
uv run cypherast explain "MATCH (a)-[:R]->(b) RETURN a"
uv run cypherast run "CREATE (n:Person {name: 'Ada'}) RETURN n"
```

Or via Make:

```bash
make help
make sync test
make check
make optimize Q="MATCH (n:Person) RETURN n.name"
make optimize Q="..." CONSTRAINT_DISABLE=strip_nulls_order_modifiers
make optimize Q="..." DISABLE=qualify,annotate_types
make validate Q="MATCH (n) RETURN n"
make translate Q="MATCH (n:Person) RETURN n" FROM=opencypher TO=puppygraph OPT=1
```

## Dialects

`opencypher` · `neo4j25` (`neo4j`/`neo`) · `neo4j5` (`cypher5`) · `memgraph` · `puppygraph` (read-only target). Gremlin/GQL generators = v1.x.

openCypher 9 spec: [openCypher9.pdf](https://s3.amazonaws.com/artifacts.opencypher.org/openCypher9.pdf).

`puppygraph` subclasses openCypher and applies engine capability constraints on optimize/translate
(reject writes, unbounded variable-length patterns, map/pattern projections and subquery
expressions; strip `NULLS FIRST/LAST`; apply FET-45 null CASE guards). Unlabelled,
undirected, and Cartesian MATCH are accepted. Bounded hop limits remain an engine /
query-guard concern. Does **not** inject `LIMIT`.

Procedure `CALL ns.proc(…) [YIELD …]` parses and renders for all dialects (including PuppyGraph
`algo.*`). Optimize leaves procedure calls as pass-through; run algorithms on the engine, not
the in-memory executor.

```python
cypherast.optimize(q, write="puppygraph").cypher(dialect="puppygraph")
cypherast.translate(q, from_="opencypher", to_="puppygraph", optimize=True)
cypherast.validate(q, dialect="puppygraph", schema=schema)  # schema= optional
```

## TCK scoreboard

Official [openCypher TCK](https://github.com/opencypher/openCypher/tree/master/tck) is **not vendored**. The runner clones it to `/tmp/opencypher` and writes `tests/tck/results.md`:

```bash
make test-tck-official          # parse + in-memory executor
make test-tck-official-parse    # parse gate only
make test-tck-oc9             # OC9-excluded scenario filter
make test-tck-dialects        # transpose OC9-passing runs → neo4j5/neo4j25/memgraph/puppygraph
```

Override feature path: `CYPHERAST_TCK_PATH=/path/to/tck/features`. Dialect matrix report: `tests/tck/results-dialects.md`.

Parse coverage expands Cucumber Scenario Outlines with `gherkin-official`; execution scores
continue to use the runner's executable subset.

| Gate | Rate |
|------|------|
| Parse (3,897 expanded scenarios) | 100% |
| Run (executable only) | ~64% |
| Effective run (+ expected errors) | ~65% |
| Dialect transpose (`neo4j5`/`neo4j25`/`memgraph`) | ~97% of OC9-passing |
| Dialect transpose (`puppygraph`, executable) | ~59% (capability skips excluded) |

**Run rate notes:** The executor runner skips outlines, side-effect checks, unparseable queries,
and procedure stubs. Parse-only coverage expands outlines and accepts a parser rejection for
compile-time-error scenarios. Scenarios that expect compile/runtime errors count as passes when
cypherast rejects the query (`expected` bucket). These targets are scoreboards, not gates: they
exit non-zero while any non-skipped scenario still fails, so read the printed rates rather than
the exit status. `make test-tck-dialects` is the gated one (it fails only below the per-dialect
floors).

## Status

v0.1.10 — versioned Neo4j dialects (`neo4j25` / `neo4j5`); capability-gated Cypher 25 and Memgraph surface; neutral Cypher core lowering before plan / execute / lineage; TCK dialect transpose matrix.

## CI

GitHub Actions (`.github/workflows/ci.yml`): ruff · mypy (strict) · pytest + coverage (fail-under 60%, uploads `coverage.xml`).

Release (`.github/workflows/release.yml`): push tag `vX.Y.Z` (must match `project.version` in `pyproject.toml`) → quality gate → `uv build` → **PyPI** (trusted publishing) → GitHub Release with wheel/sdist.

Local: `make check` · `make test-cov` · `make build`

Dry-run build locally: `make dist` then `uvx twine check dist/*`.
