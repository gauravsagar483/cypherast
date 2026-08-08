"""Validate: list concat, node IN list, list/pattern comprehension messages."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.validate.issues import ConstraintIssue


def _list_concat_ops(tree: a.AstNode) -> list[ConstraintIssue]:
    """ET-06: list concatenation via ``+`` (Add between list-ish operands)."""
    list_aliases: set[str] = set()
    list_fns = {
        "collect",
        "keys",
        "labels",
        "nodes",
        "relationships",
        "range",
        "split",
        "tail",
    }

    def _list_producing(n: a.AstNode | None) -> bool:
        if n is None:
            return False
        # Element / string index access is not a list operand
        if isinstance(n, a.ListSubscript):
            return False
        if isinstance(n, (a.List, a.ListComprehension)):
            return True
        if isinstance(n, a.FunctionCall) and str(n.name).lower() in list_fns:
            return True
        if isinstance(n, a.Identifier) and n.this in list_aliases:
            return True
        if isinstance(n, a.Add):
            return _list_producing(n.this) or _list_producing(n.expression)
        return False

    def _note_projection(expressions: list[a.AstNode] | None) -> None:
        for expr in expressions or []:
            if not isinstance(expr, a.Alias):
                continue
            alias = None
            if isinstance(expr.alias, a.Identifier):
                alias = expr.alias.this
            elif isinstance(expr.alias, str):
                alias = expr.alias
            if not alias:
                continue
            if _list_producing(expr.this):
                list_aliases.add(alias)
            else:
                list_aliases.discard(alias)

    def _adds_in(node: a.AstNode | None) -> list[a.Add]:
        if node is None:
            return []
        found: list[a.Add] = []
        if isinstance(node, a.Add):
            found.append(node)
        if hasattr(node, "find_all"):
            for add in node.find_all(a.Add):
                assert isinstance(add, a.Add)
                found.append(add)
        return found

    def _flag_list_adds(node: a.AstNode | None) -> list[ConstraintIssue] | None:
        for add in _adds_in(node):
            if _list_producing(add.this) or _list_producing(add.expression):
                return [
                    ConstraintIssue(
                        "CG1401",
                        "List concatenation (+) is not supported by this dialect",
                        hint="Avoid list + list; project with UNWIND / collect instead",
                    )
                ]
        return None

    def _scan_query(q: a.Query) -> list[ConstraintIssue]:
        nonlocal list_aliases
        list_aliases = set()
        for clause in q.clauses or []:
            if isinstance(clause, a.With):
                for expr in clause.expressions or []:
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    hit = _flag_list_adds(core)
                    if hit:
                        return hit
                hit = _flag_list_adds(clause.where)
                if hit:
                    return hit
                for sub in (clause.order, clause.skip, clause.limit):
                    hit = _flag_list_adds(sub)
                    if hit:
                        return hit
                _note_projection(clause.expressions)
            elif isinstance(clause, a.Return):
                for expr in clause.expressions or []:
                    core = expr.this if isinstance(expr, a.Alias) else expr
                    hit = _flag_list_adds(core)
                    if hit:
                        return hit
                for sub in (clause.order, clause.skip, clause.limit):
                    hit = _flag_list_adds(sub)
                    if hit:
                        return hit
            elif isinstance(clause, a.Match):
                hit = _flag_list_adds(clause.where)
                if hit:
                    return hit
            elif isinstance(clause, a.Unwind):
                hit = _flag_list_adds(clause.expression)
                if hit:
                    return hit
            elif isinstance(clause, a.Set):
                for item in clause.items or []:
                    hit = _flag_list_adds(item)
                    if hit:
                        return hit
        return []

    root = tree.this if isinstance(tree, a.Cypher) else tree
    if isinstance(root, a.Query):
        return _scan_query(root)
    if isinstance(root, a.Union):
        for q in root.find_all(a.Query):
            assert isinstance(q, a.Query)
            issues = _scan_query(q)
            if issues:
                return issues
        return []
    # Fallback: no alias tracking
    for n in tree.find_all(a.Add):
        assert isinstance(n, a.Add)
        if _list_producing(n.this) or _list_producing(n.expression):
            return [
                ConstraintIssue(
                    "CG1401",
                    "List concatenation (+) is not supported by this dialect",
                    hint="Avoid list + list; project with UNWIND / collect instead",
                )
            ]
    return []


def _node_in_list_membership(tree: a.AstNode) -> list[ConstraintIssue]:
    """ET-21: node variable on the left of ``IN`` (list membership)."""
    node_vars: set[str] = set()
    for n in tree.find_all(a.NodePattern):
        assert isinstance(n, a.NodePattern)
        if isinstance(n.variable, a.Identifier):
            node_vars.add(n.variable.this)

    def _listish_rhs(n: a.AstNode | None) -> bool:
        if n is None:
            return False
        if isinstance(n, (a.List, a.ListComprehension, a.ListSubscript)):
            return True
        if isinstance(n, a.Identifier):
            return True
        return isinstance(n, a.FunctionCall) and str(n.name).lower() in {
            "collect",
            "keys",
            "labels",
            "nodes",
            "relationships",
            "range",
            "split",
        }

    for n in tree.find_all(a.In):
        assert isinstance(n, a.In)
        left = n.this
        if isinstance(left, a.Identifier) and left.this in node_vars and _listish_rhs(n.expression):
            return [
                ConstraintIssue(
                    "CG1401",
                    "Node IN list membership is not supported by this dialect",
                    hint="Compare on a property (n.id IN [...]) instead of the node itself",
                )
            ]
    return []
