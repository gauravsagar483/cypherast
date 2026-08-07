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
| `explain` / `profile` | Cost / naive plan text |
| `run` | Execute on in-memory `Graph` |
| `lineage` | Binding-level provenance |

Full samples: [docs/api.md](docs/api.md). Guides: [docs/](docs/README.md) (AST primer, optimizer, dialects, onboarding).

### parse / parse_one

```python
tree = cypherast.parse_one(
    "MATCH (a:Person)-[:KNOWS]->(b) RETURN a.name, b.name",
    read="opencypher",  # or neo4j / memgraph
)
print(tree.cypher())
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

# optional graph catalog (id fields / undeclared props when schema.strict=True)
schema = GraphSchema()
schema.add_label("Person", name="string")
schema.add_id_field("DataQualityCheck", "dq_check_id")
cypherast.optimize(q, write="puppygraph", schema=schema)
```

### explain / profile / run

```python
from cypherast.executor import Graph

print(cypherast.explain("MATCH (n:Person)-[:KNOWS]->(m) RETURN n, m"))

g = Graph()
g.create_node(["Person"], {"name": "Ada", "age": 36})
rows = cypherast.run(
    "MATCH (n:Person) WHERE n.age > 30 RETURN n.name",
    graph=g,
)
print(list(rows))
```

### lineage

```python
root = cypherast.lineage(
    "MATCH (n:Person) RETURN n.name AS name",
    binding="name",
)
print(root)  # provenance Node; .to_html() for vis.js
```

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

`opencypher` · `neo4j` · `memgraph` · `puppygraph` (read+write). Gremlin/GQL generators = v1.x.

`puppygraph` subclasses openCypher and applies engine capability constraints on optimize/translate
(labelled MATCH, no Cartesian multi-path MATCH, strip `NULLS FIRST/LAST`, FET-45 null CASE, etc.).
Does **not** inject `LIMIT` or enforce hop caps (leave those to the engine / query_guard).

```python
cypherast.optimize(q, write="puppygraph").cypher(dialect="puppygraph")
cypherast.translate(q, from_="opencypher", to_="puppygraph", optimize=True)
cypherast.validate(q, dialect="puppygraph", schema=schema)  # schema= optional
```

## TCK scoreboard

Sample openCypher-style `.feature` files live under `tests/tck/features/`. Runner reports parse-rate:

```bash
uv run pytest tests/tck -q
```

## Status

v0.1.5 — Drop module `__version__`; single source is package metadata.

## CI

GitHub Actions (`.github/workflows/ci.yml`): ruff · mypy (strict) · pytest + coverage (fail-under 60%, uploads `coverage.xml`).

Release (`.github/workflows/release.yml`): push tag `vX.Y.Z` (must match `project.version` in `pyproject.toml`) → quality gate → `uv build` → **PyPI** (trusted publishing) → GitHub Release with wheel/sdist.

Local: `make check` · `make test-cov` · `make build`

Dry-run build locally: `make dist` then `uvx twine check dist/*`.
