# cypherglot API

Graph-native Cypher toolkit. All string I/O is **Cypher** (never SQL). AST render method is `AstNode.cypher()`.

## Import

```python
import cypherglot
from cypherglot.executor import Graph
from cypherglot.schema import GraphSchema
```

---

## `parse` / `parse_one`

```python
# Single statement → Cypher AST wrapper
tree = cypherglot.parse_one(
    "MATCH (n:Person {name: $name})-[:KNOWS*1..3]->(m) RETURN n, m",
    read="opencypher",
)
assert tree.cypher().startswith("MATCH")

# List form (one statement today)
stmts = cypherglot.parse("RETURN 1")
```

Dialects: `opencypher` (default), `neo4j`, `memgraph`, `puppygraph`.

---

## `translate` / `transpile`

Parse with source dialect, render with target dialect.

```python
src = "MATCH (n:Person) WHERE n.age > 18 RETURN n.name AS name"

print(cypherglot.translate(src, from_="opencypher", to_="neo4j", pretty=True))
print(cypherglot.transpile(src, from_="neo4j", to_="memgraph"))
```

Identity round-trip:

```python
q = "MATCH (a)-[:R]->(b) RETURN a"
assert cypherglot.translate(q, from_="opencypher", to_="opencypher")
```

---

## `optimize`

Runs named rewriter rules (default order): `qualify` → `canonicalize_patterns` →
`simplify` → `pushdown_predicates` → `annotate_types`. Then dialect **constraint**
rules (e.g. PuppyGraph `ensure_row_limit`, `split_multi_path_match`).

`merge_match_chains` is opt-in via `OPTIONAL_RULES` (Cartesian risk on some engines).

```python
from cypherglot.optimizer import RULES, OPTIONAL_RULES

optimized = cypherglot.optimize(
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
cypherglot.optimize(q, only=["simplify", "pushdown_predicates"])
cypherglot.optimize(q, disable=["qualify"])
cypherglot.optimize(q, write="puppygraph", constraint_disable=["ensure_row_limit"])
cypherglot.optimize(q, rules=RULES + OPTIONAL_RULES)
```

Optional schema:

```python
schema = GraphSchema()
schema.add_label("Person", name="string", age="integer")
cypherglot.optimize("MATCH (n:Person) RETURN n", schema=schema)
```

Accepts either Cypher text or an existing `AstNode`.

---

## `explain` / `profile`

```python
print(cypherglot.explain(
    "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name"
))

print(cypherglot.profile(
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

result = cypherglot.run(
    "MATCH (n:Person) WHERE n.age > 30 RETURN n.name AS name ORDER BY name",
    graph=g,
)
for row in result:
    print(row)  # {'name': 'Ada'}
```

Writes:

```python
cypherglot.run("CREATE (n:Person {name: 'Grace'}) RETURN n", graph=g)
cypherglot.run(
    "MATCH (n:Person {name: 'Grace'}) SET n.age = 40 REMOVE n:Temp RETURN n",
    graph=g,
)
```

---

## `lineage`

Binding-level provenance (graph analog of column lineage).

```python
node = cypherglot.lineage(
    "MATCH (n:Person) WITH n.name AS nm RETURN nm",
    binding="nm",
)
# node.expression, node.downstream, node.to_html()
```

---

## AST surface

```python
tree = cypherglot.parse_one("MATCH (n) RETURN n")
print(tree.cypher(pretty=True))
for child in tree.walk():
    ...
rewritten = tree.transform(lambda n: n)  # copy-aware rewrite hook
```

---

## CLI mirrors

| CLI | API |
|-----|-----|
| `cypherglot parse Q` | `parse_one` |
| `cypherglot translate Q -r … -w …` | `translate` |
| `cypherglot optimize Q` | `optimize(…).cypher(pretty=True)` |
| `cypherglot explain Q` | `explain` |
| `cypherglot run Q` | `run` |
