"""Reject dialect-gated constructs (Cypher 25, Memgraph, shared extensions)."""

from __future__ import annotations

from cypherast import ast as a
from cypherast.dialects.capabilities import DialectCapabilities
from cypherast.dialects.validate.issues import ConstraintIssue


def _reject_cypher25_only(tree: a.AstNode, caps: DialectCapabilities) -> list[ConstraintIssue]:
    issues: list[ConstraintIssue] = []
    if not caps.allow_filter_clause and tree.find(a.Filter):
        issues.append(
            ConstraintIssue(
                "CG1520",
                "FILTER clause requires Cypher 25 / neo4j25",
                hint="Use WHERE or target dialect neo4j25",
            )
        )
    if not caps.allow_let_clause and tree.find(a.Let):
        issues.append(
            ConstraintIssue(
                "CG1520",
                "LET clause requires Cypher 25 / neo4j25",
                hint="Use WITH or target dialect neo4j25",
            )
        )
    if not caps.allow_search_clause and tree.find(a.Search):
        issues.append(
            ConstraintIssue(
                "CG1520",
                "SEARCH clause requires Cypher 25 / neo4j25",
                hint="Target dialect neo4j25",
            )
        )
    if not caps.allow_when_query and tree.find(a.WhenQuery):
        issues.append(
            ConstraintIssue(
                "CG1520",
                "WHEN composed queries require Cypher 25 / neo4j25",
                hint="Target dialect neo4j25",
            )
        )
    if not caps.allow_for_clause and tree.find(a.For):
        issues.append(
            ConstraintIssue(
                "CG1520",
                "FOR clause requires Cypher 25 / neo4j25",
                hint="Use UNWIND or target dialect neo4j25",
            )
        )
    if not caps.allow_load_csv and tree.find(a.LoadCsv):
        issues.append(
            ConstraintIssue(
                "CG1401",
                "LOAD CSV is not supported by this dialect",
                hint="Target neo4j5, neo4j25, or memgraph",
            )
        )
    if not caps.allow_admin_ddl and tree.find(a.AdminStatement):
        issues.append(
            ConstraintIssue(
                "CG1401",
                "Admin DDL is not supported by this dialect",
                hint="Target memgraph or a dialect with allow_admin_ddl",
            )
        )
    if not caps.allow_group_by_subclause:
        for node in tree.find_all(a.With):
            assert isinstance(node, a.With)
            if node.group_by is not None:
                issues.append(
                    ConstraintIssue(
                        "CG1520",
                        "GROUP BY subclause requires Cypher 25 / neo4j25",
                    )
                )
                break
        for node in tree.find_all(a.Return):
            assert isinstance(node, a.Return)
            if node.group_by is not None:
                issues.append(
                    ConstraintIssue(
                        "CG1520",
                        "GROUP BY subclause requires Cypher 25 / neo4j25",
                    )
                )
                break
    if not caps.allow_call_variable_import:
        for call in tree.find_all(a.CallSubquery):
            assert isinstance(call, a.CallSubquery)
            if call.variables is not None:
                issues.append(
                    ConstraintIssue(
                        "CG1401",
                        "CALL (vars) { } variable import is not supported by this dialect",
                    )
                )
                break
    if not caps.allow_optional_call:
        for call in tree.find_all(a.CallSubquery):
            assert isinstance(call, a.CallSubquery)
            if call.optional:
                issues.append(
                    ConstraintIssue(
                        "CG1520",
                        "OPTIONAL CALL requires Cypher 25 / neo4j25",
                        hint="Target dialect neo4j25",
                    )
                )
                break
    if not caps.allow_call_in_transactions:
        for call in tree.find_all(a.CallSubquery):
            assert isinstance(call, a.CallSubquery)
            if call.in_transactions:
                issues.append(
                    ConstraintIssue(
                        "CG1520",
                        "CALL … IN TRANSACTIONS requires Cypher 25 / neo4j25",
                        hint="Target dialect neo4j25",
                    )
                )
                break
    if not caps.allow_inline_pattern_where:
        for element in (*tree.find_all(a.NodePattern), *tree.find_all(a.RelationshipPattern)):
            assert isinstance(element, (a.NodePattern, a.RelationshipPattern))
            if element.where is not None:
                issues.append(
                    ConstraintIssue(
                        "CG1401",
                        "Inline pattern WHERE is not supported by this dialect",
                    )
                )
                break
    if not caps.allow_label_expressions:
        for node in tree.find_all(a.LabelExpression):
            assert isinstance(node, a.LabelExpression)
            expr = node.expression or ""
            if any(ch in expr for ch in "!&%"):
                issues.append(
                    ConstraintIssue(
                        "CG1401",
                        "Label expressions (!, &, %) are not supported by this dialect",
                    )
                )
                break
    if not caps.allow_memgraph_rel_quantifiers:
        for rel in tree.find_all(a.RelationshipPattern):
            assert isinstance(rel, a.RelationshipPattern)
            if rel.memgraph_quantifier:
                issues.append(
                    ConstraintIssue(
                        "CG1521",
                        "Memgraph relationship quantifiers (*bfs, *wShortest) are not in this dialect",
                        hint="Target dialect memgraph",
                    )
                )
                break
    return issues
