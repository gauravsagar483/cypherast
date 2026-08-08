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

Dialects: `opencypher` / `opencypher9` (openCypher 9 baseline; default), `neo4j`, `memgraph`, `puppygraph`.

### Nesting depth

The parser is recursive descent, so nesting is bounded. `cypherast.parser.MAX_PARSE_DEPTH`
is `1000` (CPython's default `sys.getrecursionlimit()`), counted over statement,
expression, and path-pattern nesting; `Parser(source, max_depth=…)` overrides it.
Overflow raises `ParseError` **CG1105** (`maximum recursion depth exceeded while parsing`)
with the offending position — a bare `RecursionError` never escapes `parse()`. Because one
nesting level costs several Python frames, the interpreter stack usually trips first
(around 140 nested parentheses); both paths report CG1105.

### Procedure `CALL` vs subquery `CALL`

Two different clause shapes share the `CALL` keyword:

| Form | AST | Notes |
|------|-----|--------|
| `CALL { … }` | `CallSubquery` | Nested query (parse + render; limited exec) |
| `CALL ns.proc(args) [YIELD …] [WHERE …]` | `CallProcedure` | Procedures / graph algorithms |

```python
from cypherast import ast as a

# Neo4j / Memgraph catalog procedures
tree = cypherast.parse_one("CALL db.labels() YIELD label RETURN label")
assert tree.find(a.CallProcedure).name == "db.labels"

# PuppyGraph graph algorithms (send rendered Cypher to the engine)
q = """
CALL algo.paral.pagerank({
    labels: ['Page'],
    relationshipTypes: ['LINKS'],
    maxIterations: 20,
    dampingFactor: 0.85
}) YIELD id, score
RETURN id, score
"""
out = cypherast.optimize(q, write="puppygraph", strict=False).cypher()
# → pass `out` to Bolt / PuppyGraph; in-memory `run()` does not execute procedures
```

`YIELD` field names (and `AS` aliases) enter binding scope for CG1201. Standalone
`CALL db.ping()` with no `YIELD` is allowed. `YIELD *` is supported.

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
PuppyGraph `ensure_labelled_nodes` mines the query (and optional caller `schema=`); residual bare nodes get `:_Node`.

`optimize(..., strict=False)` returns a rewritten AST that may still fail `validate` — escape hatch only.

Accepts either Cypher text or an existing `AstNode`.

---

## `validate`

List remaining capability / schema issues for a dialect (empty = OK). Prefer
`optimize(..., write=dialect)` first when you want rewrites applied; raw validate
flags issues on the input as-is. The `opencypher` dialect emits **CG15xx** codes
for OC9 conformance (comparability, functions, patterns, clauses).

```python
issues = cypherast.validate(q, dialect="opencypher")
issues = cypherast.validate(q, dialect="puppygraph")
issues = cypherast.validate(q, dialect="puppygraph", schema=schema)
```

---

## Neutral Cypher core (semantic APIs)

`explain`, `profile`, `run`, and `lineage` do not consume dialect surface AST. They
parse with the requested dialect, then lower once to a **neutral Cypher core** before
planner / executor / lineage see the tree:

```text
parse(read=…) → [optional optimize/render for a write target] → lower_to_core → planner · executor · lineage
```

| API | Source-surface keyword |
|-----|------------------------|
| `explain` / `profile` / `run` | `read=` |
| `lineage` | `from_` (text and AST alike) |
| `cypherast.executor.execute(tree, …)` | `dialect=` |
| `cypherast.planner.explain` / `profile` / `plan_query` | `dialect=` |

```python
from cypherast.dialects.lower import lower_to_core
from cypherast.executor import execute

tree = cypherast.parse_one("FOR n IN [1, 2] RETURN n", read="neo4j25")
list(execute(tree, dialect="neo4j25"))  # [{'n': 1}, {'n': 2}]

core = lower_to_core(tree, dialect="neo4j25")  # copy; `tree` is unchanged
```

Lowering returns a copy, so source trees keep their surface nodes. The keyword only
names the source surface: lowering is structural and runs even when no dialect is
given, so the neutral-core guarantee never depends on the caller remembering it
(lowering already-core AST is idempotent).

Lowered for in-memory use: inline pattern `WHERE` (hoisted into the owning `MATCH` /
pattern comprehension), `FOR` → `UNWIND`, `FILTER` → `WITH … WHERE`, `LET` → one
`WITH` per item (sequential scope, so a later item may reference an earlier one),
redundant `GROUP BY` metadata, Memgraph `*bfs`. `CALL … IN TRANSACTIONS` batching
metadata is cleared because in-memory execution is single-process.

Rejected with `ExecuteError` (`CG1702`) rather than silently mis-executed:

| Surface | Why |
|---------|-----|
| `GROUP BY` keys ≠ the clause's non-aggregate projections | core grouping derives from projections, so clearing the keys would change aggregates |
| `GROUP BY` with no aggregate projection | grouping collapses duplicate rows; core projection keeps them |
| `FILTER` item whose predicate ignores its own binding | core `WITH * WHERE …` filters the whole row, losing the item's scope |
| Inline `WHERE` on a variable-length relationship | the binding is a relationship list, not a scalar to hoist |
| Inline `WHERE` inside `shortestPath` / quantified path | the predicate belongs to search / repetition semantics |
| `wShortest`, `SEARCH`, `LOAD CSV`, admin statements, `WHEN` | no core equivalent |

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

Pass `read=` to name the source surface, e.g. `explain("MATCH (n:Person WHERE n.age
> 18) RETURN n", read="neo4j25")` plans a `Filter` over the hoisted predicate.

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

# `from_` names the source surface; LET lowers to WITH before provenance walks
node = cypherast.lineage(
    "MATCH (n:Person) LET age = n.age RETURN age",
    binding="age",
    from_="neo4j25",
)
```

RETURN bindings resolve backwards from the `RETURN`, so a later `WITH` shadows an
earlier alias of the same name. Repeated names stop the walk, so `WITH n AS n` and
alias cycles terminate with the last useful expression instead of recursing.

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
