"""Validate: unlabelled MATCH node patterns."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _unlabelled_nodes(tree: a.AstNode) -> list[ConstraintIssue]:
    """MATCH/OPTIONAL MATCH nodes must be labelled on first bind.

    Bare ``(var)`` reuse is OK when ``var`` was already bound with a label
    earlier in the same query (after WITH, only projected labelled names remain).
    ``UNWIND collect(node) AS x`` then ``(x)`` counts as bound reuse.
    Anonymous ``()`` and new unlabelled ``(x)`` always fail.
    """
    issues: list[ConstraintIssue] = []
    labelled: set[str] = set()
    node_lists: set[str] = set()  # aliases of collect(labelled_node)

    def _label_names(n: a.NodePattern) -> list[str]:
        if isinstance(n.labels, a.LabelExpression):
            if n.labels.expression:
                return [str(n.labels.expression)]
            return list(n.labels.labels or [])
        return []

    def _collect_of_labelled(expr: a.AstNode) -> bool:
        core = expr.this if isinstance(expr, a.Alias) else expr
        if not isinstance(core, a.FunctionCall):
            return False
        if str(core.name).lower() != "collect":
            return False
        args = core.expressions or []
        if len(args) == 1 and isinstance(args[0], a.Identifier):
            return args[0].this in labelled
        return False

    def _alias_name(expr: a.AstNode) -> str | None:
        if isinstance(expr, a.Alias):
            if isinstance(expr.alias, a.Identifier):
                return str(expr.alias.this)
            if isinstance(expr.alias, str):
                return expr.alias
        return None

    def _check_match(match: a.Match) -> None:
        if not isinstance(match.pattern, a.Pattern):
            return
        for n in match.pattern.walk():
            if not isinstance(n, a.NodePattern):
                continue
            labels = _label_names(n)
            var = n.variable.this if isinstance(n.variable, a.Identifier) else None
            if labels:
                if var:
                    labelled.add(var)
                continue
            if var is not None and var in labelled:
                continue
            where = f"({var})" if var else "()"
            issues.append(
                ConstraintIssue(
                    "CG1402",
                    f"Unlabelled node pattern {where} is not allowed by this dialect",
                    hint="Write (var:Label) on first bind; never () or new (var) without a label",
                )
            )

    def _apply_with(clause: a.With) -> None:
        nonlocal labelled, node_lists
        if any(isinstance(expr, a.Star) for expr in (clause.expressions or [])):
            # WITH * keeps prior labelled / list bindings
            return
        nxt: set[str] = set()
        nxt_lists: set[str] = set()
        for expr in clause.expressions or []:
            alias = _alias_name(expr)
            if _collect_of_labelled(expr) and alias:
                nxt_lists.add(alias)
            if isinstance(expr, a.Alias):
                src = expr.this.this if isinstance(expr.this, a.Identifier) else None
                if src in labelled and alias:
                    nxt.add(alias)
                elif src in node_lists and alias:
                    nxt_lists.add(alias)
            elif isinstance(expr, a.Identifier):
                if expr.this in labelled:
                    nxt.add(expr.this)
                if expr.this in node_lists:
                    nxt_lists.add(expr.this)
        labelled = nxt
        node_lists = nxt_lists

    def _apply_unwind(clause: a.Unwind) -> None:
        nonlocal labelled
        alias = (
            clause.alias.this
            if isinstance(clause.alias, a.Identifier)
            else clause.alias
            if isinstance(clause.alias, str)
            else None
        )
        src = clause.expression
        from_list = (
            isinstance(src, a.Identifier) and src.this in node_lists
        ) or _collect_of_labelled(src)
        if alias and from_list:
            labelled.add(alias)

    root: a.AstNode | None = tree
    if isinstance(tree, a.Cypher) and isinstance(tree.this, a.Query):
        root = tree.this
    if isinstance(root, a.Query) and root.clauses:
        for clause in root.clauses:
            if isinstance(clause, a.Match):
                _check_match(clause)
            elif isinstance(clause, a.With):
                _apply_with(clause)
            elif isinstance(clause, a.Unwind):
                _apply_unwind(clause)
        return issues

    for match in tree.find_all(a.Match):
        assert isinstance(match, a.Match)
        _check_match(match)
    return issues
