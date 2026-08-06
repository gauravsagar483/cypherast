# cypherglot

Cypher/GQL transpiler, rewriter, cost-based planner, and in-memory executor.

Zero runtime dependencies. Python 3.13+. Graph-native API — no SQL vocabulary.

## Install

```bash
# from source (dev)
uv sync --group dev

# from PyPI (after a release tag)
pip install cypherglot
# or: uv add cypherglot
```

## Quick start

```python
import cypherglot

q = "MATCH (n:Person) WHERE n.age > 30 RETURN n.name"
tree = cypherglot.parse_one(q)
print(tree.cypher(pretty=True))

print(cypherglot.optimize(q).cypher(pretty=True))

print(cypherglot.translate(q, from_="opencypher", to_="neo4j", pretty=True))
# alias:
print(cypherglot.transpile(q, from_="opencypher", to_="memgraph"))
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

Full samples: [docs/api.md](docs/api.md).

### parse / parse_one

```python
tree = cypherglot.parse_one(
    "MATCH (a:Person)-[:KNOWS]->(b) RETURN a.name, b.name",
    read="opencypher",  # or neo4j / memgraph
)
print(tree.cypher())
```

### translate (transpile)

```python
out = cypherglot.translate(
    "MATCH (n:Person) RETURN n",
    from_="opencypher",
    to_="neo4j",
    pretty=True,
)
print(out)
```

### optimize

Folds `WHERE n.x = lit` into `(n {x: lit})`, simplifies expressions. Rules are named
and toggleable:

```python
from cypherglot.optimizer import RULES, OPTIONAL_RULES

print(
    cypherglot.optimize(
        "MATCH (n:Person) WHERE n.status = 'ACTIVE' RETURN n"
    ).cypher(pretty=True)
)
# MATCH (n:Person {status: 'ACTIVE'}) RETURN n

# disable / only
cypherglot.optimize(q, disable=["qualify", "annotate_types"])
cypherglot.optimize(q, write="puppygraph", constraint_disable=["ensure_row_limit"])
cypherglot.optimize(q, rules=RULES + OPTIONAL_RULES)  # opt-in merge_match_chains
```

### explain / profile / run

```python
from cypherglot.executor import Graph

print(cypherglot.explain("MATCH (n:Person)-[:KNOWS]->(m) RETURN n, m"))

g = Graph()
g.create_node(["Person"], {"name": "Ada", "age": 36})
rows = cypherglot.run(
    "MATCH (n:Person) WHERE n.age > 30 RETURN n.name",
    graph=g,
)
print(list(rows))
```

### lineage

```python
root = cypherglot.lineage(
    "MATCH (n:Person) RETURN n.name AS name",
    binding="name",
)
print(root)  # provenance Node; .to_html() for vis.js
```

## CLI

```bash
uv run cypherglot parse "MATCH (n) RETURN n"
uv run cypherglot translate "MATCH (n) RETURN n" -r opencypher -w neo4j --pretty
uv run cypherglot optimize "MATCH (n:Person) WHERE n.x = 1 RETURN n"
uv run cypherglot explain "MATCH (a)-[:R]->(b) RETURN a"
uv run cypherglot run "CREATE (n:Person {name: 'Ada'}) RETURN n"
```

Or via Make:

```bash
make help
make sync test
make check
make optimize Q="MATCH (n:Person) RETURN n.name"
make optimize Q="..." CONSTRAINT_DISABLE=ensure_row_limit
make optimize Q="..." DISABLE=qualify,annotate_types
make validate Q="MATCH (n) RETURN n"
make translate Q="MATCH (n:Person) RETURN n" FROM=opencypher TO=puppygraph OPT=1
```

## Dialects

`opencypher` · `neo4j` · `memgraph` · `puppygraph` (read+write). Gremlin/GQL generators = v1.x.

`puppygraph` subclasses openCypher and applies engine capability constraints on optimize/translate
(LIMIT, labelled MATCH, bounded hops, no Cartesian multi-path MATCH, etc.).

```python
cypherglot.optimize(q, write="puppygraph").cypher(dialect="puppygraph")
cypherglot.translate(q, from_="opencypher", to_="puppygraph", optimize=True)
cypherglot.validate(q, dialect="puppygraph")
```

## TCK scoreboard

Sample openCypher-style `.feature` files live under `tests/tck/features/`. Runner reports parse-rate:

```bash
uv run pytest tests/tck -q
```

## Status

v0.1 — P0–P5 core + P5.1 hardening (Cypher naming, parser edge cases, richer planner, docs).

## CI

GitHub Actions (`.github/workflows/ci.yml`): ruff · mypy (strict) · pytest + coverage (fail-under 60%, uploads `coverage.xml`).

Release (`.github/workflows/release.yml`): push tag `vX.Y.Z` (must match `project.version` in `pyproject.toml`) → quality gate → `uv build` → **PyPI** (trusted publishing) → GitHub Release with wheel/sdist.

Local: `make check` · `make test-cov` · `make build`

### Publishing to PyPI

Publisher account: [gsagar on PyPI](https://pypi.org/user/gsagar/)

1. **One-time setup (trusted publishing — no API token in GitHub secrets)**
   - Log in as **gsagar** on [pypi.org](https://pypi.org).
   - Until the project exists: [Publishing settings → pending publisher](https://pypi.org/manage/account/publishing/) (or after first upload: project → **Publishing**):
     - PyPI project name: `cypherglot`
     - Owner: your GitHub user/org (same account that owns the repo)
     - Repository: `cypherglot`
     - Workflow name: `release.yml`
     - Environment name: `pypi`
   - GitHub repo → **Settings → Environments → New environment** named `pypi` (optional required reviewers).

2. **Cut a release**
   ```bash
   # bump version in pyproject.toml (e.g. 0.1.0 → 0.1.1), commit
   git tag -a v0.1.1 -m "v0.1.1"
   git push origin main
   git push origin v0.1.1
   ```
   Tag **must** be `v` + exact `project.version`. Workflow refuses mismatched tags.

3. **Verify**
   - Actions → **Release** workflow green
   - Package shows under [pypi.org/user/gsagar/](https://pypi.org/user/gsagar/)
   - `pip install cypherglot==0.1.1`
   - GitHub → Releases has notes + `dist/*` artifacts

Dry-run build locally: `make dist` then `uvx twine check dist/*`.
