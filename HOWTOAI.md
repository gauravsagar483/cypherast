# How to Use AI with cypherast

Practical guide for contributing with AI coding assistants.

## Core principles

- Human owns the PR. Understand every line before merge.
- Match existing graph-native style: Cypher terms, zero runtime deps, typed Python 3.13.
- Read `AGENTS.md` and `.agents/rules/` before large changes.
- Never invent dialect limits — open `cypherast/dialects/capabilities.py` and `constraints.py`.

## Best workflow

1. Sync env: `uv sync --group dev`
2. Reproduce with a minimal Cypher string via `parse_one` / `optimize` / `translate`
3. Prefer TDD for parser/rewriter/dialect behavior (`tests/test_*.py`)
4. Run `make check` (ruff + mypy + pytest) before claiming done
5. For PuppyGraph emit path: also `make test-puppy` and `make validate Q="..."`

### Useful Make targets

```bash
make help
make optimize Q="MATCH (n:Person) WHERE n.status = 'ACTIVE' RETURN n.name"
make optimize Q="..." WRITE=puppygraph CONSTRAINT_DISABLE=ensure_row_limit
make translate Q="..." FROM=opencypher TO=puppygraph OPT=1
make validate Q="MATCH (n) RETURN n" DIALECT=puppygraph
```

### Named optimizer rules

```python
import cypherast
from cypherast.optimizer import RULES, OPTIONAL_RULES

cypherast.optimize(q, disable=["qualify"])
cypherast.optimize(q, write="puppygraph", constraint_disable=["ensure_row_limit"])
cypherast.optimize(q, rules=RULES + OPTIONAL_RULES)  # opt-in merge_match_chains
```

## What to watch

- Do not merge MATCH chains into comma paths by default — PuppyGraph rejects Cartesian multi-path MATCH.
- Pattern predicates must not introduce new bindings; do not qualify anon vars inside them.
- `AstNode.cypher(dialect=...)` for render checks after optimize/translate.
- Keep `merge_match_chains` out of default `RULES` unless explicitly opting in.

## Review bar for AI-authored PRs

- Tests cover the behavior change (parser, rewriter, dialect, or API).
- Docs/README/api only updated when the public surface changed.
- No SQL-clone framing in comments or docs (see `.agents/rules/graph-native-naming.md`).
- `make check` green locally.

## Tools

- Canonical instructions: `AGENTS.md`
- Shared rules: `.agents/rules/` only
- Copilot (optional): `.github/copilot-instructions.md`
- Full API samples: `docs/api.md`
