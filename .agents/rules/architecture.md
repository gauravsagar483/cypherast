---
description: Pipeline layers and module boundaries for cypherast
alwaysApply: true
---

# Architecture

Pipeline order (do not skip layers or import backwards):

1. **Lexer / parser** (`lexer.py`, `parser.py`) → AST (`ast.py`)
2. **Dialect** (`dialects/`) — parse/render hooks, `capabilities`, constraint rewrites
3. **Rewriter passes** (`rewriter/`) — pure AST transforms
4. **Optimizer** (`optimizer/`) — named `Rule` / `RuleSet`, catalogs, `only`/`disable`
5. **Planner** (`planner/`) — explain / cost / physical ops
6. **Executor** (`executor/`) — in-memory `Graph` + engine

## Rules

- Public surface stays in `cypherast/__init__.py` (+ CLI). New user-facing entry points go there.
- Dialect-specific engine limits belong in `DialectCapabilities` + `constraints.py` / `constraint_rules`, not hard-coded label/rel names from one customer graph.
- Rewrite implementations live in `rewriter/`; registration/order/names live in `optimizer/catalog.py`.
- Rendering goes through `Renderer` / `AstNode.cypher(...)` — keep dialect emit differences in dialect renderer subclasses when needed.
- Avoid circular imports: `rewriter/__init__.py` must not import `optimizer` at module top level (optimizer catalog imports rewriter pass modules).

## Anti-patterns

- SQL vocabulary or SQL-toolchain brand names in APIs/docs
- Putting PuppyGraph (or any engine) hacks into shared openCypher paths without a capability flag
- Enabling `merge_match_chains` by default
