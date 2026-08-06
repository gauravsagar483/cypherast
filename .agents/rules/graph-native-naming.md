---
description: Keep cypherast graph-native — no SQL-clone framing or foreign brand names
alwaysApply: true
---

# Graph-native naming

cypherast is a **Cypher/GQL** library. Do not frame it as a SQL toolchain clone in code, comments, docs, tests, READMEs, commit messages, or user-facing copy. Do not cite third-party SQL library brand names.

## Do

- Describe features in graph/Cypher terms: named rewrite rules, dialects, `only`/`disable`, capability constraints.
- Use graph-native vocabulary (MATCH, pattern, binding, hop).

## Don't

```text
# BAD
"SQL-style optimizer like <sql library>"
"transpile_sql" / AstNode.sql()
customer- or employer-specific product codenames in public docs
```

```text
# GOOD
"named rule filters"
"enable/disable by rule name"
AstNode.cypher()
generic engine capability limits
```

Keep the idea; drop foreign brand names and internal org jargon from the public repo.
