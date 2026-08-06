Feature: MatchAcceptance
  Sample openCypher TCK-style scenarios for cypherast parse-rate scoreboard.

  Scenario: Match and return node
    When executing query:
      """
      MATCH (n)
      RETURN n
      """
    Then the result should be empty

  Scenario: Match with label and property
    When executing query:
      """
      MATCH (n:Person {name: 'Ada'})
      RETURN n.name
      """
    Then the result should be empty

  Scenario: Match relationship pattern
    When executing query:
      """
      MATCH (a:Person)-[:KNOWS]->(b:Person)
      RETURN a.name, b.name
      """
    Then the result should be empty

  Scenario: Optional match
    When executing query:
      """
      MATCH (n:Person)
      OPTIONAL MATCH (n)-[:KNOWS]->(m)
      RETURN n, m
      """
    Then the result should be empty

  Scenario: Where clause equality
    When executing query:
      """
      MATCH (n:Person)
      WHERE n.age > 30 AND n.status = 'ACTIVE'
      RETURN n
      """
    Then the result should be empty
