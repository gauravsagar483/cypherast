Feature: CreateAcceptance
  Write clause parse samples.

  Scenario: Create node
    When executing query:
      """
      CREATE (n:Person {name: 'Ada'})
      RETURN n
      """
    Then the result should be empty

  Scenario: Merge node
    When executing query:
      """
      MERGE (n:Person {name: 'Ada'})
      ON CREATE SET n.created = true
      RETURN n
      """
    Then the result should be empty

  Scenario: Set and remove property
    When executing query:
      """
      MATCH (n:Person)
      SET n.age = 36
      REMOVE n.temp
      RETURN n
      """
    Then the result should be empty

  Scenario: Remove label
    When executing query:
      """
      MATCH (n:Person:Temp)
      REMOVE n:Temp
      RETURN n
      """
    Then the result should be empty

  Scenario: Foreach create
    When executing query:
      """
      FOREACH (x IN [1, 2] | CREATE (:Num {v: x}))
      """
    Then the result should be empty

  Scenario: Delete detach
    When executing query:
      """
      MATCH (n:Person)
      DETACH DELETE n
      """
    Then the result should be empty
