"""Bidirectional transpile of real web Cypher across dialects."""

from __future__ import annotations

import pytest

import cypherast
from tests.fixtures.web_cypher_queries import DIALECTS, WEB_CYPHER_QUERIES


@pytest.mark.parametrize("qid,src,cypher", WEB_CYPHER_QUERIES, ids=[q[0] for q in WEB_CYPHER_QUERIES])
def test_parse_in_source_dialect(qid: str, src: str, cypher: str) -> None:
    tree = cypherast.parse_one(cypher, read=src)
    assert tree is not None


@pytest.mark.parametrize("qid,src,cypher", WEB_CYPHER_QUERIES, ids=[q[0] for q in WEB_CYPHER_QUERIES])
@pytest.mark.parametrize(
    "from_,to_",
    [(a, b) for a in DIALECTS for b in DIALECTS if a != b],
    ids=[f"{a}->{b}" for a in DIALECTS for b in DIALECTS if a != b],
)
def test_plain_transpile_roundtrip(
    qid: str, src: str, cypher: str, from_: str, to_: str
) -> None:
    """A→B→A stable under plain transpile (no optimize)."""
    fwd = cypherast.transpile(cypher, from_=from_, to_=to_, optimize=False)
    back = cypherast.transpile(fwd, from_=to_, to_=from_, optimize=False)
    again = cypherast.transpile(back, from_=from_, to_=to_, optimize=False)
    again2 = cypherast.transpile(again, from_=to_, to_=from_, optimize=False)
    assert again2 == back


@pytest.mark.parametrize(
    "qid,cypher",
    [
        (q[0], q[2])
        for q in WEB_CYPHER_QUERIES
        if q[0]
        in {
            "neo4j-keanu",
            "pg-cocreators",
            "mg-call-with",
            "mg-call-cartesian",
            "neo4j-path-star",
            "pg-prop-marko",
            "mg-proc-list",
        }
    ],
)
@pytest.mark.parametrize(
    "from_,to_",
    [
        ("neo4j", "memgraph"),
        ("memgraph", "neo4j"),
        ("neo4j", "puppygraph"),
        ("puppygraph", "neo4j"),
        ("opencypher", "puppygraph"),
        ("puppygraph", "opencypher"),
    ],
    ids=lambda p: f"{p[0]}->{p[1]}" if isinstance(p, tuple) else str(p),
)
def test_optimize_transpile_directional(
    qid: str, cypher: str, from_: str, to_: str
) -> None:
    """optimize=True uses TARGET dialect caps only."""
    if qid in {"mg-call-cartesian", "mg-call-with"} and to_ in {
        "opencypher",
        "puppygraph",
        "opencypher9",
    }:
        pytest.skip("openCypher 9 rejects CALL subqueries")
    out = cypherast.transpile(cypher, from_=from_, to_=to_, optimize=True)
    assert "MATCH" in out.upper() or "CALL" in out.upper() or "UNWIND" in out.upper()
    # Round-trip parse in target
    cypherast.parse_one(out, read=to_)
    if to_ == "puppygraph":
        # Residual :_Node / CALL exports — no CG1402 / CG1201 after optimize path
        issues = cypherast.validate(out, read=to_, dialect=to_)
        assert not any(i.code == "CG1402" for i in issues)
        assert not any(i.code == "CG1201" for i in issues)
