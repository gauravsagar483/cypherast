import pytest

import cypherast
from cypherast import ast as a
from cypherast.errors import TokenizeError


@pytest.mark.parametrize(
    ("cypher", "value"),
    [
        ("RETURN 0x1 AS literal", 1),
        ("RETURN 0x1A2b AS literal", 0x1A2B),
        ("RETURN 0o77 AS literal", 0o77),
        ("RETURN 01 AS literal", 1),
        ("RETURN -0x1 AS literal", -1),
        ("RETURN -0o10 AS literal", -8),
    ],
)
def test_parse_radix_integer_literals(cypher: str, value: int) -> None:
    tree = cypherast.parse_one(cypher, read="opencypher")
    literal = tree.find(a.Integer)
    assert isinstance(literal, a.Integer)
    assert literal.this == abs(value)
    if value < 0:
        assert tree.find(a.Neg) is not None


@pytest.mark.parametrize("cypher", ["RETURN 0x", "RETURN 0xG", "RETURN 0o8"])
def test_reject_invalid_radix_integer_literals(cypher: str) -> None:
    with pytest.raises(TokenizeError):
        cypherast.parse_one(cypher, read="opencypher")


@pytest.mark.parametrize(
    "body",
    [
        "(n)-->()",
        "(n)-->(m) WHERE n.prop = m.prop",
        "(n)-[:NA]->()",
        "(n)-[r]->() WHERE type(r) = 'NA'",
    ],
)
def test_parse_bare_pattern_inside_exists_subquery(body: str) -> None:
    tree = cypherast.parse_one(
        f"MATCH (n) WHERE EXISTS {{ {body} }} RETURN n",
        read="opencypher",
    )
    predicate = tree.find(a.PatternPredicate)
    assert isinstance(predicate, a.PatternPredicate)
    assert isinstance(predicate.pattern, a.Query)
    assert predicate.pattern.find(a.PathPattern) is not None


@pytest.mark.parametrize("target", ["(n).name", "(r).name"])
def test_parse_parenthesized_set_property_target(target: str) -> None:
    tree = cypherast.parse_one(
        f"MATCH (n)-[r:REL]->(m) SET {target} = 'value' RETURN n",
        read="opencypher",
    )
    item = tree.find(a.SetItem)
    assert isinstance(item, a.SetItem)
    assert isinstance(item.this, a.Property)
    assert item.this.name == "name"


def test_parse_bidirectional_relationship_after_anonymous_node() -> None:
    tree = cypherast.parse_one(
        "MATCH (a)-[:LIKES]->()<-[:LIKES*3]->(c) RETURN a, c",
        read="opencypher",
    )
    rels = tree.find_all(a.RelationshipPattern)
    assert len(rels) == 2
    assert rels[1].direction is a.Direction.BOTH
    assert rels[1].min_hops == 3
    assert rels[1].max_hops == 3
