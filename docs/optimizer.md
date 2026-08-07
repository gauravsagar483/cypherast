# Optimizer and constraint rules

cypherast’s “optimize” path is two layers:

1. **Canonicalizer** — shared rewrite passes (`RULES`)
2. **Dialect constraints** — capability-driven rewrites / rejects (`constraint_rules`)

Public entry: `cypherast.optimize(...)` (also used by `Dialect.optimize` / `translate(..., optimize=True)`).

## Default canonicalizer order

From [`cypherast/optimizer/catalog.py`](../cypherast/optimizer/catalog.py):

1. `qualify`
2. `canonicalize_patterns`
3. `simplify`
4. `pushdown_predicates`
5. `annotate_types`

Opt-in (not default — Cartesian risk on some engines):

- `OPTIONAL_RULES` → `merge_match_chains`

```python
from cypherast.optimizer import RULES, OPTIONAL_RULES
import cypherast

cypherast.optimize(q, only=["simplify", "pushdown_predicates"])
cypherast.optimize(q, disable=["qualify"])
cypherast.optimize(q, rules=RULES + OPTIONAL_RULES)
```

Implementations live under `cypherast/optimizer/` (canonicalizer) and `cypherast/dialects/transforms/` (capability rewrites). Names/order live in `optimizer/catalog.py`. `cypherast/rewriter/` is a shim only.

## Constraint rules

Built from `DialectCapabilities` via `constraint_rules(caps)`. Examples for PuppyGraph:

| Rule | Role |
|------|------|
| `ensure_labelled_nodes` | Fill missing MATCH labels from schema / neighbor fallback |
| `strip_nulls_order_modifiers` | Drop `NULLS FIRST/LAST` |
| `guard_optional_scalar_use` | FET-45: `CASE WHEN var IS NULL …` around OPTIONAL `id()`/`split`/… |

Filter with `constraint_only` / `constraint_disable`:

```python
cypherast.optimize(
    q,
    write="puppygraph",
    constraint_disable=["strip_nulls_order_modifiers"],
)
```

Some capabilities are **reject-only** (no rewrite): e.g. multi-`collect(DISTINCT)`, Cartesian comma MATCH, `DISTINCT` beside aggregates. Those surface as `ValidationError` when `strict=True`.

## `strict` (default True)

After rewrites, `optimize` runs the same checks as `validate` and **raises** on leftover issues (`CG12xx`–`CG14xx`).

```python
# Default: raise if still invalid for the write dialect
cypherast.optimize(q, write="puppygraph")

# Soft AST (may still fail validate)
cypherast.optimize(q, write="puppygraph", strict=False)
```

`translate(..., optimize=True)` follows the same raise behavior by default.

## Schema catalog

Pass `schema=GraphSchema(...)` into `optimize` / `validate`:

- Labelling help for `ensure_labelled_nodes`
- **CG1305** if an `id_field` is used as `n.prop`
- When `schema.strict=True` (closed-world):
  - **CG1301** unknown node labels
  - **CG1302** unknown relationship types
  - **CG1303** undeclared props on *known* labels/rels

`GraphSchema.strict` defaults to **False** (open-world for unknown names). Without a
caller schema, domain catalogs are a non-goal.

```python
from cypherast.schema import GraphSchema

schema = GraphSchema()
schema.add_label("Person", name="string")
schema.add_id_field("DataQualityCheck", "dq_check_id")
# schema.strict = True  # closed-world labels/rels + undeclared props

cypherast.optimize(q, write="puppygraph", schema=schema)
cypherast.validate(q, dialect="puppygraph", schema=schema)
```

## Non-goals (intentionally not rewritten here)

- Injecting `LIMIT` on every row-returning query
- Capping / rejecting variable-length hop bounds (leave to query_guard / engine)
- Inventing undeclared domain properties without a caller `GraphSchema`

## Rule author checklist

1. Implement pure AST transform in `optimizer/` **or** engine rewrite in `dialects/transforms/` / reject in `dialects/validate/`.
2. Register a named `Rule` in `optimizer/catalog.py` (canonical) or `constraint_rules` (capability-gated).
3. Add tests under `tests/test_optimizer_rules.py` / dialect tests.
4. Document capability flags in `DialectCapabilities` when adding engine limits.

Next: [dialects.md](dialects.md) · [ast_primer.md](ast_primer.md) · [api.md](api.md)
