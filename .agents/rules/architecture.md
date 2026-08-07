---
description: Pipeline layers and module boundaries for cypherast
alwaysApply: true
---

# Architecture

Pipeline order (do not skip layers or import backwards):

1. **Lexer / parser** (`lexer.py`, `parser.py`) → AST (`ast.py`)
2. **Dialect** (`dialects/`) — parse/render hooks, `capabilities`, transforms, validate
3. **Optimizer** (`optimizer/`) — named IR passes + `Rule` / `RuleSet` catalog (`only`/`disable`)
4. **Planner** (`planner/`) — explain / cost / physical ops
5. **Executor** (`executor/`) — in-memory `Graph` + engine

## File classification (non-overlapping)

| Concern | Own here | Not here |
|---------|----------|----------|
| Capability knobs (bools, frozensets, limits) | `dialects/capabilities.py` + dialect class | hardcoded sets in transform/validate bodies |
| Dialect **rewrites** | `dialects/transforms/` | `validate/`, `optimizer/` canonical RULES |
| Dialect **reject-only checks** | `dialects/validate/` | `transforms/` |
| Facade re-exports | `dialects/constraints.py` (thin) | new logic |
| Shared IR canonicalize | `optimizer/` (qualify, simplify, …) | `dialects/` |
| Back-compat shim | `rewriter/` → re-exports `optimizer` | new passes |

## Rules

- Public surface stays in `cypherast/__init__.py` (+ CLI). New user-facing entry points go there.
- Dialect-specific engine limits belong in `DialectCapabilities` + `constraint_rules(caps)`, not hard-coded label/rel names from one customer graph.
- Rewrite implementations for engines live in `dialects/transforms/`; registration/order/names live in `optimizer/catalog.py`.
- Rendering goes through `Renderer` / `AstNode.cypher(...)` — keep dialect emit differences in dialect renderer subclasses when needed.
- Avoid circular imports: `rewriter/` may import `optimizer` only as a shim; catalog must not import `rewriter`.

## Anti-patterns

- SQL vocabulary or SQL-toolchain brand names in APIs/docs
- Putting PuppyGraph (or any engine) hacks into shared openCypher paths without a capability flag
- Enabling `merge_match_chains` by default
- Growing a megafile that mixes transforms + validate
