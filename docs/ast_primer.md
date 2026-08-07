# Primer on cypherast’s abstract syntax tree

cypherast parses Cypher into a single IR (`AstNode` subclasses). This post covers how to read that tree, walk it, and change it.

## The tree

```python
import cypherast
from cypherast import ast as a

tree = cypherast.parse_one(
    "MATCH (n:Person)-[:KNOWS]->(m:Person) WHERE n.age > 30 RETURN n.name"
)
```

The best way to see structure is `repr`:

```python
repr(tree)
# Cypher(this=Query(clauses=[
#   Match(
#     pattern=Pattern(paths=[PathPattern(elements=[
#       NodePattern(variable=Identifier(this='n'), labels=LabelExpression(labels=['Person'])),
#       RelationshipPattern(types=['KNOWS'], direction=<Direction.OUTGOING: 1>),
#       NodePattern(variable=Identifier(this='m'), labels=LabelExpression(labels=['Person'])),
#     ])]),
#     where=Where(this=GT(this=Property(...), expression=Integer(this=30))),
#   ),
#   Return(expressions=[Property(this=Identifier(this='n'), name='name')]),
# ]))
```

Render back to Cypher with `.cypher()` (optionally `pretty=True`, `dialect=…`):

```python
print(tree.cypher(pretty=True))
# MATCH (n:Person)-[:KNOWS]->(m:Person)
# WHERE n.age > 30
# RETURN n.name
```

## Nodes of the tree

Every construct subclasses `cypherast.ast.AstNode`.

- Children live in `node.args` (also exposed as attributes via `__getattr__`).
- Parent is `node.parent` (set when you use `set` / constructors carefully).
- Each class declares `arg_types`: keys of children; `True` means required.

```python
class Property(a.AstNode):
    arg_types = {"this": True, "name": True}  # n.age → this=Identifier, name="age"
```

Common keys:

| Key | Typical use |
|-----|-------------|
| `this` | Primary child (e.g. left side of a binary, subject of a property) |
| `expression` | Secondary child (e.g. right side of a comparison) |
| `expressions` | List of children (e.g. `RETURN` items) |

There is **one** AST vocabulary for all dialects. Dialects differ in parse/render/capabilities, not in a separate node catalog.

Clause highlights:

| Node | Cypher shape |
|------|----------------|
| `CallSubquery` | `CALL { MATCH … RETURN … }` |
| `CallProcedure` | `CALL algo.wcc({…}) YIELD id, componentId` |
| `Yield` | Field list on a procedure `CALL` (including `YIELD *`) |

Browse types in [`cypherast/ast.py`](../cypherast/ast.py).

## Traversing

### Direct `args`

When you know the shape:

```python
q = tree.this  # Query
assert isinstance(q, a.Query)
match = q.clauses[0]
assert isinstance(match, a.Match)
```

### `walk` / `find` / `find_all`

```python
# Depth-first over AstNode children
for node in tree.walk():
    ...

tree.find(a.Match)                 # first Match, or None
tree.find_all(a.Property)          # all Property nodes
[p.cypher() for p in tree.find_all(a.Property)]
# ['n.age', 'n.name']
```

> **Pitfall:** `find_all` is structural, not semantic. A `NodePattern` inside a `WHERE` pattern predicate is not the same as a `MATCH` binder. For binding scope, use [`cypherast.scope`](../cypherast/scope.py) / lineage — see below.

### Scope and lineage

`cypherast.scope.build_scope` tracks bindings across `WITH` / `UNWIND` / `UNION` / procedure `CALL` `YIELD`. Binding-level provenance is exposed as `cypherast.lineage(...)`:

```python
node = cypherast.lineage(
    "MATCH (n:Person) WITH n.name AS nm RETURN nm",
    binding="nm",
)
# node.expression, node.downstream, node.to_html()
```

## Mutating the tree

### `set` / construct nodes

Prefer `AstNode.set` (or attribute assignment) so `parent` links stay correct:

```python
ident = a.Identifier(this="n")
prop = a.Property(this=ident, name="age")
```

### `transform`

Depth-first rewrite. Return a new node to replace, or `None` / the same node to keep:

```python
def bump_ages(node: a.AstNode) -> a.AstNode | None:
    if isinstance(node, a.Integer) and node.parent and isinstance(node.parent, a.GT):
        return a.Integer(this=int(node.this) + 1)
    return node

rewritten = tree.transform(bump_ages)
print(rewritten.cypher())
# ... WHERE n.age > 31 ...
```

Pass `copy=False` to mutate in place (optimizer rules often do this after an initial copy).

### High-level API

For most product work, prefer public entrypoints instead of hand-building trees:

```python
import cypherast

opt = cypherast.optimize(
    "MATCH (n:Person) WHERE n.status = 'ACTIVE' RETURN n.name",
    write="puppygraph",
)
print(opt.cypher(dialect="puppygraph"))
```

## Summed up

1. Parse → `AstNode` tree; render with `.cypher()`.
2. Traverse with `args`, `walk` / `find` / `find_all`, or scope/lineage when bindings matter.
3. Mutate with `set`, `transform`, or `optimize` / dialect constraints.

Next: [optimizer.md](optimizer.md) · [dialects.md](dialects.md) · [api.md](api.md)
