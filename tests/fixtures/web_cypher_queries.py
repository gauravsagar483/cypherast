"""Real Cypher samples from public dialect docs (for transpile roundtrips).

Sources:
- Neo4j Cypher Manual (MATCH / basic queries)
- PuppyGraph Cypher QL docs
- Memgraph CALL / procedures docs
"""

from __future__ import annotations

# (id, source_dialect_hint, cypher)
WEB_CYPHER_QUERIES: list[tuple[str, str, str]] = [
    # Neo4j — https://neo4j.com/docs/cypher-manual/current/clauses/match/
    ("neo4j-match-all", "neo4j", "MATCH (n) RETURN n"),
    ("neo4j-movie-title", "neo4j", "MATCH (movie:Movie) RETURN movie.title"),
    (
        "neo4j-oliver-stone",
        "neo4j",
        "MATCH (:Person {name: 'Oliver Stone'})-->(movie:Movie) "
        "RETURN movie.title AS movieTitle",
    ),
    (
        "neo4j-where-filter",
        "neo4j",
        "MATCH (charlie:Person)-[:ACTED_IN]->(movie:Movie) "
        "WHERE charlie.name = 'Charlie Sheen' RETURN movie.title AS movieTitle",
    ),
    (
        "neo4j-keanu",
        "neo4j",
        "MATCH (keanu:Person {name:'Keanu Reeves'}) "
        "RETURN keanu.name AS name, keanu.born AS born",
    ),
    ("neo4j-limit", "neo4j", "MATCH (people:Person) RETURN people LIMIT 5"),
    (
        "neo4j-path-star",
        "neo4j",
        "MATCH p = (keanu:Person {name: 'Keanu Reeves'})-[r]->(m) RETURN *",
    ),
    # PuppyGraph — https://docs.puppygraph.com/reference/cypher-query-language/
    ("pg-all-nodes", "puppygraph", "MATCH (v) RETURN v"),
    ("pg-person-label", "puppygraph", "MATCH (v:person) RETURN v"),
    ("pg-prop-marko", "puppygraph", "MATCH (v {name: 'marko'}) RETURN v"),
    ("pg-where-age", "puppygraph", "MATCH (v) WHERE v.age > 30 RETURN v"),
    (
        "pg-cocreators",
        "puppygraph",
        "MATCH (u:person {name:'marko'})-[:created]->(:software)"
        "<-[:created]-(v:person) RETURN v.name",
    ),
    (
        "pg-with-pipe",
        "puppygraph",
        "MATCH ({name: 'marko'})-[:knows]->(v) WITH v "
        "MATCH (v)-[:created]->(x) "
        "RETURN v.name AS otherPerson, x.name AS Software",
    ),
    ("pg-unwind", "puppygraph", "UNWIND ['a', 'b', 'b'] as x RETURN x"),
    # Memgraph — https://memgraph.com/docs/querying/clauses/call
    (
        "mg-call-cartesian",
        "memgraph",
        "MATCH (p:Person) CALL { MATCH (a:Animal) RETURN a.name as animal_name } "
        "RETURN p.name as person_name, animal_name",
    ),
    (
        "mg-call-with",
        "memgraph",
        "MATCH (person:Person) CALL { WITH person "
        "MATCH (person)-[:HAS_PARENT]->(parent:Parent) RETURN parent } "
        "RETURN person.name, parent.name",
    ),
    (
        "mg-proc-list",
        "memgraph",
        "CALL mg.procedures() YIELD name, signature RETURN name, signature",
    ),
    (
        "oc-optional",
        "opencypher",
        "MATCH (a:Person) OPTIONAL MATCH (a)-[:KNOWS]->(b:Person) "
        "RETURN a.name, b.name",
    ),
    (
        "oc-collect",
        "opencypher",
        "MATCH (a:Person)-[:ACTED_IN]->(m:Movie) "
        "RETURN a.name, collect(m.title) AS movies",
    ),
]

DIALECTS = ("opencypher", "neo4j", "memgraph", "puppygraph")
