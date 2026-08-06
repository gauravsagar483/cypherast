# cypherast API

Graph-native Cypher toolkit. All string I/O is **Cypher** (never SQL). AST render method is `AstNode.cypher()`.

## Import

```python
import cypherast
from cypherast.executor import Graph
from cypherast.schema import GraphSchema
```

---

## `parse` / `parse_one`

```python
# Single statement → Cypher AST wrapper
tree = cypherast.parse_one(
    "MATCH (n:Person {name: $name})-[:KNOWS*1..3]->(m) RETURN n, m",
    read="opencypher",
)
assert tree.cypher().startswith("MATCH")

# List form (one statement today)
stmts = cypherast.parse("RETURN 1")
```

Dialects: `opencypher` (default), `neo4j`, `memgraph`, `puppygraph`.

---

## `translate` / `transpile`

Parse with source dialect, render with target dialect.

```python
src = "MATCH (n:Person) WHERE n.age > 18 RETURN n.name AS name"

print(cypherast.translate(src, from_="opencypher", to_="neo4j", pretty=True))
print(cypherast.transpile(src, from_="neo4j", to_="memgraph"))
```

Identity round-trip:

```python
q = "MATCH (a)-[:R]->(b) RETURN a"
assert cypherast.translate(q, from_="opencypher", to_="opencypher")
```

---

## `optimize`

Runs named rewriter rules (default order): `qualify` → `canonicalize_patterns` →
`simplify` → `pushdown_predicates` → `annotate_types`. Then dialect **constraint**
rules (e.g. PuppyGraph `ensure_row_limit`, `split_multi_path_match`).

`merge_match_chains` is opt-in via `OPTIONAL_RULES` (Cartesian risk on some engines).

```python
from cypherast.optimizer import RULES, OPTIONAL_RULES

optimized = cypherast.optimize(
    """
    MATCH (n:Person)
    WHERE n.status = 'ACTIVE' AND n.age > 21
    RETURN n.name
    """
)
print(optimized.cypher(pretty=True))
# Property equality folded into the node pattern when safe:
# MATCH (n:Person {status: 'ACTIVE'}) WHERE n.age > 21 RETURN n.name

# named rule filters
cypherast.optimize(q, only=["simplify", "pushdown_predicates"])
cypherast.optimize(q, disable=["qualify"])
cypherast.optimize(q, write="puppygraph", constraint_disable=["ensure_row_limit"])
cypherast.optimize(q, rules=RULES + OPTIONAL_RULES)
```

Optional schema:

```python
schema = GraphSchema()
schema.add_label("Person", name="string", age="integer")
cypherast.optimize("MATCH (n:Person) RETURN n", schema=schema)
```

Accepts either Cypher text or an existing `AstNode`.

---

## `explain` / `profile`

```python
print(cypherast.explain(
    "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name"
))

print(cypherast.profile(
    "MATCH (n:Person) RETURN count(n)",
    graph=Graph(),
))
```

With `GraphSchema` stats/indexes, cost enumeration picks lower-cost scan anchors.

---

## `run`

Execute against an in-memory property graph.

```python
g = Graph()
g.create_node(["Person"], {"name": "Ada", "age": 36})
g.create_node(["Person"], {"name": "Bob", "age": 22})

result = cypherast.run(
    "MATCH (n:Person) WHERE n.age > 30 RETURN n.name AS name ORDER BY name",
    graph=g,
)
for row in result:
    print(row)  # {'name': 'Ada'}
```

Writes:

```python
cypherast.run("CREATE (n:Person {name: 'Grace'}) RETURN n", graph=g)
cypherast.run(
    "MATCH (n:Person {name: 'Grace'}) SET n.age = 40 REMOVE n:Temp RETURN n",
    graph=g,
)
```

---

## `lineage`

Binding-level provenance (graph analog of column lineage).

```python
node = cypherast.lineage(
    "MATCH (n:Person) WITH n.name AS nm RETURN nm",
    binding="nm",
)
# node.expression, node.downstream, node.to_html()
```

---

## AST surface

```python
tree = cypherast.parse_one("MATCH (n) RETURN n")
print(tree.cypher(pretty=True))
for child in tree.walk():
    ...
rewritten = tree.transform(lambda n: n)  # copy-aware rewrite hook
```

---

## CLI mirrors

| CLI | API |
|-----|-----|
| `cypherast parse Q` | `parse_one` |
| `cypherast translate Q -r … -w …` | `translate` |
| `cypherast optimize Q` | `optimize(…).cypher(pretty=True)` |
| `cypherast explain Q` | `explain` |
| `cypherast run Q` | `run` |
