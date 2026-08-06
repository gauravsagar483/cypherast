Feature: ExpressionAcceptance
  Expression / function / comprehension parse samples.

  Scenario: List subscript
    When executing query:
      """
      RETURN split('a.b.c', '.')[1] AS mid
      """
    Then the result should be empty

  Scenario: Pattern comprehension
    When executing query:
      """
      MATCH (n:Person)
      RETURN [(n)-[:KNOWS]->(m) | m.name] AS friends
      """
    Then the result should be empty

  Scenario: List comprehension
    When executing query:
      """
      RETURN [x IN range(1, 5) WHERE x > 2 | x * 2] AS xs
      """
    Then the result should be empty

  Scenario: Exists pattern
    When executing query:
      """
      MATCH (n:Person)
      WHERE EXISTS ((n)-[:KNOWS]->())
      RETURN n
      """
    Then the result should be empty

  Scenario: Not pattern predicate
    When executing query:
      """
      MATCH (n:Person)
      WHERE NOT (n)-[:KNOWS]->()
      RETURN n
      """
    Then the result should be empty

  Scenario: Call subquery
    When executing query:
      """
      MATCH (n:Person)
      CALL {
        MATCH (m:Person) RETURN m LIMIT 1
      }
      RETURN n
      """
    Then the result should be empty

  Scenario: Quantified path pattern
    When executing query:
      """
      MATCH ((a)-[:KNOWS]->(b)){1,3}
      RETURN a, b
      """
    Then the result should be empty

  Scenario: String functions
    When executing query:
      """
      MATCH (n:Person)
      WHERE toLower(n.name) = 'ada'
      RETURN toString(n.age), trim(n.name), replace(n.name, 'a', 'A')
      """
    Then the result should be empty
