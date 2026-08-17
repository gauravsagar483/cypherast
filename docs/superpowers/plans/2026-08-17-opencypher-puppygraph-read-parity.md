# OpenCypher and PuppyGraph Read Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cypherast parse, render, optimize, and validate the verified
read-only PuppyGraph Cypher surface while preserving strict openCypher 9.

**Architecture:** Shared syntax and signatures stay generic. Immutable
`DialectCapabilities` owns engine policy; PuppyGraph declares deltas from
`OPENCYPHER9_CAPABILITIES`. Focused validators reject unsupported AST nodes.

**Tech Stack:** Python 3.11+, pytest, Ruff, mypy, zero runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-17-opencypher-puppygraph-read-parity-design.md`

## Global Constraints

- Graph-native naming only.
- No runtime dependencies.
- No customer-specific labels or relationship types.
- No silent rewrites of unsupported semantics.
- Unit tests do not require a live engine.

---

### Task 1: Shared regex syntax

**Files:**
- Modify: `cypherast/lexer.py`
- Modify: `cypherast/ast.py`
- Modify: `cypherast/parser.py`
- Modify: `cypherast/renderer.py`
- Test: `tests/test_opencypher.py`

**Interfaces:**
- Produces: an AST expression for `lhs =~ rhs` that round-trips through
  `parse_one(...).cypher()`.

- [ ] Add a failing public round-trip test for `RETURN 'abc' =~ 'a.*' AS ok`.
- [ ] Run the focused test and confirm lexer failure on `~`.
- [ ] Add token, AST node, parser precedence, and renderer support.
- [ ] Run focused parser/OpenCypher tests.

### Task 2: Function metadata and dialect policy

**Files:**
- Modify: `cypherast/schema.py`
- Modify: `cypherast/dialects/capabilities.py`
- Modify: `cypherast/dialects/validate/functions.py`
- Modify: `cypherast/dialects/validate/dispatch.py`
- Test: `tests/test_opencypher.py`
- Test: `tests/test_puppygraph_dialect.py`

**Interfaces:**
- Produces: capability fields for allowed excluded names, unsupported names,
  and `(name, min_args, max_args)` arity overrides.
- Consumes: shared function signatures and specialized `Coalesce`/`Quantifier`
  AST nodes.

- [ ] Add failing tests for temporal functions, `range` step, strict OC9
  exclusions, PuppyGraph allowances/denials, and coalesce arity.
- [ ] Confirm expected CG1507/CG1508/CG1509 failures.
- [ ] Extend shared metadata and capability-driven function validation.
- [ ] Run focused function tests.

### Task 3: Shared quantifier scope

**Files:**
- Modify: `cypherast/scope.py`
- Modify: `cypherast/dialects/validate/undefined_vars.py`
- Test: `tests/test_puppygraph_dialect.py`

**Interfaces:**
- Produces: lexical scope for quantifier binders without leaking them outside
  the expression.

- [ ] Add failing tests for `all`, `any`, and `none`.
- [ ] Confirm CG1201 on each binder.
- [ ] Teach scope/reference collection about `Quantifier`.
- [ ] Run focused scope tests.

### Task 4: Generic capability gates

**Files:**
- Modify: `cypherast/dialects/capabilities.py`
- Create: focused modules under `cypherast/dialects/validate/`
- Modify: `cypherast/dialects/validate/dispatch.py`
- Modify: `cypherast/dialects/validate/id_predicates.py`
- Test: `tests/test_puppygraph_dialect.py`

**Interfaces:**
- Produces: gates for map projection, pattern/EXISTS/count subqueries,
  multi-label nodes, writes, and separate id/elementId string behavior.

- [ ] Add one failing test per gate through public optimize/validate APIs.
- [ ] Confirm unsupported PuppyGraph constructs currently pass.
- [ ] Add focused reject-only validators and dispatch gates.
- [ ] Run focused capability tests.

### Task 5: PuppyGraph capability overlay

**Files:**
- Modify: `cypherast/dialects/puppygraph.py`
- Modify: existing PuppyGraph tests whose old expectations contradict live
  engine evidence.
- Test: `tests/test_puppygraph_dialect.py`
- Test: `tests/test_puppygraph_bugbash.py`

**Interfaces:**
- Consumes: all generic capability fields from Tasks 2 and 4.
- Produces: verified read-only PuppyGraph policy.

- [ ] Add golden accept/reject parameterized tests from the probe report.
- [ ] Confirm old list/pattern/label/unbounded expectations fail.
- [ ] Flip only PuppyGraph deltas.
- [ ] Remove or disable the `:_Node` rewrite by setting labelled-node policy
  correctly; verify bare MATCH stays bare.
- [ ] Run `make test-puppy`.

### Task 6: Full and live verification

**Files:**
- Modify only when failures expose an in-scope regression.

- [ ] Run Ruff and mypy on changed modules.
- [ ] Run full `make check`.
- [ ] Run `drafts/puppy_surface_probe.py` against puppygraph-local.
- [ ] Compare changed supported/unsupported outcomes to golden tests.
- [ ] Inspect git diff and report remaining gaps separately.
