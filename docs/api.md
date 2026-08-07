# cypherast API

Graph-native Cypher toolkit. All string I/O is **Cypher** (never SQL). AST render method is `AstNode.cypher()`.

Related guides: [AST primer](ast_primer.md) · [Optimizer](optimizer.md) · [Dialects](dialects.md) · [Onboarding](onboarding.md) · [Index](README.md)

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
rules (e.g. PuppyGraph `ensure_labelled_nodes`, `strip_nulls_order_modifiers`,
`guard_optional_scalar_use`).

After rewrites, **`strict=True` by default**: remaining capability/schema issues raise
`ValidationError` (same codes as `validate`). Pass `strict=False` for a soft AST.

`merge_match_chains` is opt-in via `OPTIONAL_RULES` (Cartesian risk on some engines).

PuppyGraph does **not** inject `LIMIT` and does **not** cap variable-length hops
(leave those to the engine / query_guard).

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
cypherast.optimize(q, write="puppygraph", constraint_disable=["strip_nulls_order_modifiers"])
cypherast.optimize(q, rules=RULES + OPTIONAL_RULES)
```

Optional schema (catalog for labels, rel types, properties, id fields):

```python
schema = GraphSchema()  # strict=False by default — open-world unknown names
schema.add_label("Person", name="string", age="integer")
schema.add_id_field("DataQualityCheck", "dq_check_id")
schema.add_label("DataQualityCheck", status="string")
# Closed-world: CG1301/CG1302 unknown labels/rels + CG1303 undeclared props
# schema.strict = True

cypherast.optimize("MATCH (n:Person) RETURN n", schema=schema)

# Reject id-as-property — optimize raises (same codes as validate):
# cypherast.optimize(
#     "MATCH (dq:DataQualityCheck) RETURN dq.dq_check_id",
#     write="puppygraph", schema=schema,
# )  # → ValidationError CG1305

cypherast.optimize(
    "MATCH (dq:DataQualityCheck) RETURN id(dq)",
    write="puppygraph",
    schema=schema,
)
```

Without a caller schema, undeclared domain properties / id-fields are not checked (non-goal).
PuppyGraph's tutorial default schema is non-strict and only used for labelling.

`optimize(..., strict=False)` returns a rewritten AST that may still fail `validate` — escape hatch only.

Accepts either Cypher text or an existing `AstNode`.

---

## `validate`

List remaining capability / schema issues for a dialect (empty = OK). Prefer
`optimize(..., write=dialect)` first when you want rewrites applied; raw validate
flags issues on the input as-is.

```python
issues = cypherast.validate(q, dialect="puppygraph")
issues = cypherast.validate(q, dialect="puppygraph", schema=schema)
```

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
