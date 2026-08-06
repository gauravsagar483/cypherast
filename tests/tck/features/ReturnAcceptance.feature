Feature: ReturnAcceptance
  RETURN / WITH / UNWIND / ORDER BY samples.

  Scenario: Return literal
    When executing query:
      """
      RETURN 1 AS n
      """
    Then the result should be, in any order:
      | n |
      | 1 |

  Scenario: With and return
    When executing query:
      """
      MATCH (n:Person)
      WITH n.name AS name
      RETURN name
      """
    Then the result should be empty

  Scenario: Unwind list
    When executing query:
      """
      UNWIND [1, 2, 3] AS x
      RETURN x
      """
    Then the result should be, in order:
      | x |
      | 1 |
      | 2 |
      | 3 |

  Scenario: Order by and limit
    When executing query:
      """
      MATCH (n:Person)
      RETURN n.name AS name
      ORDER BY name DESC
      SKIP 0
      LIMIT 10
      """
    Then the result should be empty

  Scenario: Distinct aggregation
    When executing query:
      """
      MATCH (n:Person)
      RETURN count(DISTINCT n) AS c
      """
    Then the result should be empty
