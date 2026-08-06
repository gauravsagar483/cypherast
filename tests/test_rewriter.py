"""Rewriter tests."""

import cypherglot
from cypherglot import ast as a


def test_simplify_arithmetic():
    tree = cypherglot.optimize("RETURN 1 + 1")
    ret = tree.find(a.Return)
    assert ret is not None
    expr = ret.expressions[0]
    assert isinstance(expr, a.Integer)
    assert expr.this == 2


def test_simplify_boolean():
    tree = cypherglot.optimize("RETURN true AND false")
    ret = tree.find(a.Return)
    assert isinstance(ret.expressions[0], a.Boolean)
    assert ret.expressions[0].this is False


def test_qualify_names_anonymous():
    tree = cypherglot.optimize("MATCH () RETURN 1")
    node = tree.find(a.NodePattern)
    assert node is not None
    assert node.variable is not None


def test_pushdown_predicate():
    tree = cypherglot.optimize("MATCH (n:Person) WHERE n.age = 30 RETURN n")
    node = tree.find(a.NodePattern)
    assert node is not None
    assert isinstance(node.properties, a.Map)
    keys = [k for k, _ in node.properties.entries]
    assert "age" in keys
