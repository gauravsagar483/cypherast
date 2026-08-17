# OpenCypher and PuppyGraph Read Parity Design

## Goal

Model the verified PuppyGraph read-query surface without weakening the strict
openCypher 9 dialect, while making future dialects express differences through
`DialectCapabilities` instead of validator hard-coding.

## Architecture

Shared syntax belongs to the lexer, parser, AST, and renderer. Shared function
metadata belongs to `schema.py`. Engine policy belongs to immutable
`DialectCapabilities`; each dialect supplies only deltas from defaults.
Reject-only checks remain under `dialects/validate/`.

`DialectCapabilities` gains:

- function allow/deny sets and per-function arity overrides;
- independent gates for `id()` and `elementId()` string predicates;
- gates for map projection, EXISTS subquery, multi-label nodes, and writes.

PuppyGraph continues to derive from `OPENCYPHER9_CAPABILITIES`, then overrides
only verified engine differences.

## Shared OpenCypher Changes

- Parse/render `=~` regex matching.
- Catalog temporal and verified scalar functions.
- Correct `range(start, end[, step])`.
- Scope quantifier binders in `all`, `any`, `none`, and `single`.
- Validate specialized AST nodes such as `Coalesce` and `Quantifier`.

Strict `opencypher` keeps its standard exclusions. Function metadata describes
syntax/signatures; dialect policy decides availability.

## PuppyGraph Read Surface

Allow verified constructs:

- unlabelled nodes, list comprehensions, list concatenation;
- undirected relationships, `CALL { ... }`, `exists(prop)`;
- `elementId()` in string predicates;
- bounded variable-length patterns, including exact and ranged forms.

Reject verified unsupported constructs:

- pattern comprehensions, map projections, EXISTS/count subqueries;
- unbounded variable-length patterns, multi-label node patterns;
- write/admin clauses;
- unsupported functions and PuppyGraph-specific arities;
- `id()` in string predicates.

No optimizer may invent `:_Node`; unsupported input must produce a stable
constraint issue instead of silently changing result cardinality.

## Parameters

Parameter syntax remains parseable and renderable. Live PuppyGraph behavior is
inconsistent (`$p` fails while `$map.field` succeeds), so this change does not
claim general parameter support. PuppyGraph validation rejects direct parameter
expressions while allowing property access only if the AST can distinguish it
reliably; otherwise all parameter use is rejected conservatively.

## Testing

- Unit tests use public APIs and no network.
- Golden PuppyGraph accept/reject tables encode live-engine findings.
- Every production change begins with a failing test.
- Verification: focused tests, `make test-puppy`, `make check`, then the
  throwaway live probe against `puppygraph-local`.

## Non-goals

- Write-query support.
- In-memory executor parity for temporal functions or regex.
- Customer-specific labels, relationship types, or property catalogs.
- Changing Neo4j or Memgraph capabilities without evidence.
