"""Validate: schema catalog (labels, rel types, properties, id-fields)."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue
from cypherast.schema import GraphSchema


def _atomic_from_label_expr(labels: object | None) -> list[str]:
    """Flatten a ``LabelExpression`` into atomic names (split ``a|b``)."""
    raw: list[str] = []
    if isinstance(labels, a.LabelExpression):
        if labels.expression:
            raw.append(str(labels.expression))
        else:
            raw.extend(str(x) for x in (labels.labels or []))
    out: list[str] = []
    for item in raw:
        for part in str(item).split("|"):
            name = part.strip()
            # Skip complex Neo4j label ops (!, &, %) — closed-world is for plain names
            if name and not any(c in name for c in "!&%"):
                out.append(name)
    return out


def _atomic_label_names(n: a.NodePattern) -> list[str]:
    return _atomic_from_label_expr(n.labels)


def _note_unknown_label(
    lab: str,
    *,
    seen: set[str],
    schema: GraphSchema,
    issues: list[ConstraintIssue],
) -> None:
    if lab in seen:
        return
    seen.add(lab)
    if not schema.has_label(lab):
        issues.append(
            ConstraintIssue(
                "CG1301",
                f"Unknown label `{lab}`",
                hint="Declare it on GraphSchema or fix the label name",
            )
        )


def _schema_unknown_types(
    tree: a.AstNode, schema: GraphSchema
) -> list[ConstraintIssue]:
    """Closed-world label / rel-type check when ``schema.strict``.

    ``schema is None`` callers never reach here. Non-strict schemas keep
    open-world ignore (PuppyGraph tutorial default).
    """
    if not schema.strict:
        return []

    seen_labels: set[str] = set()
    seen_rels: set[str] = set()
    issues: list[ConstraintIssue] = []

    for n in tree.find_all(a.NodePattern):
        assert isinstance(n, a.NodePattern)
        for lab in _atomic_label_names(n):
            _note_unknown_label(lab, seen=seen_labels, schema=schema, issues=issues)

    for n in tree.find_all(a.RemoveLabels):
        assert isinstance(n, a.RemoveLabels)
        for lab in _atomic_from_label_expr(n.labels):
            _note_unknown_label(lab, seen=seen_labels, schema=schema, issues=issues)

    for n in tree.find_all(a.RelationshipPattern):
        assert isinstance(n, a.RelationshipPattern)
        for rt in (str(t) for t in (n.types or []) if t):
            # Rel type OR may appear as single "A|B" or separate list entries
            for part in rt.split("|"):
                name = part.strip()
                if not name or name in seen_rels:
                    continue
                seen_rels.add(name)
                if not schema.has_rel(name):
                    issues.append(
                        ConstraintIssue(
                            "CG1302",
                            f"Unknown relationship type `{name}`",
                            hint="Declare it on GraphSchema or fix the type name",
                        )
                    )
    return issues


def _schema_property_access(
    tree: a.AstNode, schema: GraphSchema
) -> list[ConstraintIssue]:
    """Reject id-field / undeclared property access when labels/types are known.

    Id-field markers always reject (``n.id_col`` → use ``id(n)``). Undeclared
    properties reject only when ``schema.strict`` and the label/rel is in schema.
    Unknown labels/types: see ``_schema_unknown_types`` (strict closed-world).
    """

    def _label_names(n: a.NodePattern) -> list[str]:
        return _atomic_label_names(n)

    def _alias_name(expr: a.AstNode) -> str | None:
        if isinstance(expr, a.Alias):
            if isinstance(expr.alias, a.Identifier):
                return str(expr.alias.this)
            if isinstance(expr.alias, str):
                return expr.alias
        if isinstance(expr, a.Identifier):
            return str(expr.this)
        return None

    def _bind_pattern(
        pattern: a.AstNode | None,
        node_vars: dict[str, set[str]],
        rel_vars: dict[str, set[str]],
    ) -> None:
        if pattern is None:
            return
        for n in pattern.walk():
            if isinstance(n, a.NodePattern):
                labs = {x for x in _label_names(n) if "|" not in x}
                if isinstance(n.variable, a.Identifier) and labs:
                    node_vars.setdefault(n.variable.this, set()).update(labs)
            elif isinstance(n, a.RelationshipPattern):
                types = {str(t) for t in (n.types or []) if t}
                if isinstance(n.variable, a.Identifier) and types:
                    rel_vars.setdefault(n.variable.this, set()).update(types)

    def _check_prop_against_labels(
        var: str, prop: str, labels: set[str]
    ) -> ConstraintIssue | None:
        known = [lb for lb in labels if schema.has_label(lb)]
        if not known:
            return None
        if any(schema.is_id_property(lb, prop) for lb in known):
            return ConstraintIssue(
                "CG1305",
                f"`{var}.{prop}` is an id field, not a map property",
                hint=f"Use id({var}) or elementId({var}) instead of {var}.{prop}",
            )
        if schema.strict and not any(schema.has_property(lb, prop) for lb in known):
            return ConstraintIssue(
                "CG1303",
                f"Unknown property `{prop}` on label(s) {', '.join(sorted(known))}",
                hint="Declare it on GraphSchema or remove the access",
            )
        return None

    def _check_prop_against_rels(
        var: str, prop: str, types: set[str]
    ) -> ConstraintIssue | None:
        known = [rt for rt in types if schema.has_rel(rt)]
        if not known:
            return None
        if any(schema.is_rel_id_property(rt, prop) for rt in known):
            return ConstraintIssue(
                "CG1305",
                f"`{var}.{prop}` is an id field, not a map property",
                hint=f"Use id({var}) or elementId({var}) instead of {var}.{prop}",
            )
        if schema.strict and not any(schema.has_rel_property(rt, prop) for rt in known):
            return ConstraintIssue(
                "CG1303",
                f"Unknown property `{prop}` on relationship type(s) "
                f"{', '.join(sorted(known))}",
                hint="Declare it on GraphSchema or remove the access",
            )
        return None

    def _map_keys(props: a.AstNode | None) -> list[str]:
        if not isinstance(props, a.Map):
            return []
        keys: list[str] = []
        for entry in props.entries or []:
            if isinstance(entry, tuple) and entry:
                keys.append(str(entry[0]))
            elif isinstance(entry, str):
                keys.append(entry)
        return keys

    def _check_inline_maps(pattern: a.AstNode | None) -> list[ConstraintIssue]:
        out: list[ConstraintIssue] = []
        if pattern is None:
            return out
        for n in pattern.walk():
            if isinstance(n, a.NodePattern):
                labs = {x for x in _label_names(n) if "|" not in x}
                var = n.variable.this if isinstance(n.variable, a.Identifier) else "?"
                for key in _map_keys(n.properties):
                    issue = _check_prop_against_labels(var, key, labs)
                    if issue:
                        out.append(issue)
            elif isinstance(n, a.RelationshipPattern):
                types = {str(t) for t in (n.types or []) if t}
                var = n.variable.this if isinstance(n.variable, a.Identifier) else "?"
                for key in _map_keys(n.properties):
                    issue = _check_prop_against_rels(var, key, types)
                    if issue:
                        out.append(issue)
        return out

    def _scan_props(
        node: a.AstNode | None,
        node_vars: dict[str, set[str]],
        rel_vars: dict[str, set[str]],
    ) -> list[ConstraintIssue]:
        if node is None:
            return []
        out: list[ConstraintIssue] = []
        for p in node.find_all(a.Property):
            assert isinstance(p, a.Property)
            if not isinstance(p.this, a.Identifier):
                continue
            var = p.this.this
            prop = str(p.name)
            if var in node_vars:
                issue = _check_prop_against_labels(var, prop, node_vars[var])
                if issue:
                    out.append(issue)
                    continue
            if var in rel_vars:
                issue = _check_prop_against_rels(var, prop, rel_vars[var])
                if issue:
                    out.append(issue)
        for mp in node.find_all(a.MapProjection):
            assert isinstance(mp, a.MapProjection)
            if not isinstance(mp.this, a.Identifier):
                continue
            var = mp.this.this
            for entry in mp.entries or []:
                key: str | None = None
                if isinstance(entry, str):
                    key = entry
                elif isinstance(entry, a.PropertySelector):
                    key = str(entry.name)
                elif isinstance(entry, tuple) and entry:
                    key = str(entry[0])
                if not key:
                    continue
                if var in node_vars:
                    issue = _check_prop_against_labels(var, key, node_vars[var])
                    if issue:
                        out.append(issue)
                elif var in rel_vars:
                    issue = _check_prop_against_rels(var, key, rel_vars[var])
                    if issue:
                        out.append(issue)
        return out

    def _check_query(q: a.Query) -> list[ConstraintIssue]:
        issues: list[ConstraintIssue] = []
        node_vars: dict[str, set[str]] = {}
        rel_vars: dict[str, set[str]] = {}
        for clause in q.clauses or []:
            if isinstance(clause, a.Match):
                issues.extend(_check_inline_maps(clause.pattern))
                _bind_pattern(clause.pattern, node_vars, rel_vars)
                issues.extend(_scan_props(clause.where, node_vars, rel_vars))
            elif isinstance(clause, (a.Create, a.Merge)):
                issues.extend(_check_inline_maps(clause.pattern))
                _bind_pattern(clause.pattern, node_vars, rel_vars)
            elif isinstance(clause, a.With):
                issues.extend(_scan_props(clause, node_vars, rel_vars))
                nxt_nodes: dict[str, set[str]] = {}
                nxt_rels: dict[str, set[str]] = {}
                for expr in clause.expressions or []:
                    alias = _alias_name(expr)
                    if alias is None:
                        continue
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    if isinstance(core, a.Identifier):
                        if core.this in node_vars:
                            nxt_nodes[alias] = set(node_vars[core.this])
                        if core.this in rel_vars:
                            nxt_rels[alias] = set(rel_vars[core.this])
                node_vars, rel_vars = nxt_nodes, nxt_rels
            elif isinstance(clause, a.Return):
                issues.extend(_scan_props(clause, node_vars, rel_vars))
            elif isinstance(clause, a.Unwind):
                issues.extend(_scan_props(clause.expression, node_vars, rel_vars))
                # UNWIND list alias is not a labelled node unless prior collect —
                # leave bindings unchanged for non-alias; drop unknown.
        return issues

    root = tree.this if isinstance(tree, a.Cypher) else tree
    if isinstance(root, a.Query):
        return _check_query(root)
    if isinstance(root, a.Union):
        out: list[ConstraintIssue] = []
        for br in root.walk():
            if isinstance(br, a.Query):
                out.extend(_check_query(br))
        return out
    # Fallback: bind all patterns then scan whole tree
    node_vars: dict[str, set[str]] = {}
    rel_vars: dict[str, set[str]] = {}
    for m in tree.find_all(a.Match, a.Create, a.Merge):
        _bind_pattern(getattr(m, "pattern", None), node_vars, rel_vars)
    return _scan_props(tree, node_vars, rel_vars)
