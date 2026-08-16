"""
Neo4j graph layer.

Per the locked design (see DEVIATIONS_FROM_PROMPT.md section H / the
methodology review): Neo4j is used specifically for path/loop/journey
queries where it is genuinely more convenient than Parquet+SQL, not as a
generic data dump. Flat aggregates (friction scores, department stats,
KPI numbers for the Overview dashboard page) stay in Parquet - they don't
benefit from a graph representation and are cheaper to query there.

Graph schema:

    (:Patient {case_id})
        -[:PERFORMED {sequence_index}]->
    (:Event {activity, timestamp, org_group, section, activity_code})

    (:Activity {name})   -- distinct activity nodes, one per unique
                              concept:name, used for the aggregated
                              transition-frequency graph below

    (:Activity)-[:NEXT_ACTIVITY {count}]->(:Activity)
        -- aggregated, dataset-wide transition frequency between
           consecutive DISTINCT activities (used for loop/pattern
           analysis and the Process Explorer dashboard page)

This module does NOT claim Neo4j is faster than SQL for arbitrary queries
(per the master prompt's explicit instruction not to assert this without
demonstrating it) - its value here is expressive, indexable path queries
(variable-length loop detection, common sub-sequences), which are
awkward self-joins in SQL and natural Cypher here.

Requires: pip install neo4j (see requirements.txt) and a running Neo4j
instance (see docker-compose.yml).
"""

from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase


class Neo4jJourneyLoader:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jJourneyLoader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def ensure_constraints(self) -> None:
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT patient_case_id IF NOT EXISTS "
                "FOR (p:Patient) REQUIRE p.case_id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT activity_name IF NOT EXISTS "
                "FOR (a:Activity) REQUIRE a.name IS UNIQUE"
            )

    def load_patient_journey(self, case_id: str, events: list[dict[str, Any]], friction_score: float | None = None) -> None:
        """
        events: list of dicts sorted chronologically, each with keys
        activity, timestamp_iso, org_group, section, activity_code
        (activity_code optional).
        """
        with self._driver.session() as session:
            session.run(
                """
                MERGE (p:Patient {case_id: $case_id})
                SET p.friction_score = $friction_score
                """,
                case_id=case_id,
                friction_score=friction_score,
            )

            for idx, ev in enumerate(events):
                session.run(
                    """
                    MATCH (p:Patient {case_id: $case_id})
                    CREATE (e:Event {
                        activity: $activity,
                        timestamp: $timestamp,
                        org_group: $org_group,
                        section: $section,
                        sequence_index: $idx
                    })
                    CREATE (p)-[:PERFORMED {sequence_index: $idx}]->(e)
                    """,
                    case_id=case_id,
                    activity=ev.get("activity"),
                    timestamp=ev.get("timestamp_iso"),
                    org_group=ev.get("org_group"),
                    section=ev.get("section"),
                    idx=idx,
                )

    def load_activity_transition_graph(self, transition_counts: dict[tuple[str, str], int]) -> None:
        """transition_counts: {(from_activity, to_activity): count}, built
        dataset-wide from consecutive-DISTINCT-activity pairs per case."""
        with self._driver.session() as session:
            for (from_act, to_act), count in transition_counts.items():
                session.run(
                    """
                    MERGE (a:Activity {name: $from_act})
                    MERGE (b:Activity {name: $to_act})
                    MERGE (a)-[r:NEXT_ACTIVITY]->(b)
                    SET r.count = $count
                    """,
                    from_act=from_act,
                    to_act=to_act,
                    count=count,
                )

    # -------------------------------------------------------------------
    # Example analytical queries used by the Streamlit dashboard.
    # -------------------------------------------------------------------

    def get_patient_journey(self, case_id: str) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (p:Patient {case_id: $case_id})-[r:PERFORMED]->(e:Event)
                RETURN e.activity AS activity, e.timestamp AS timestamp,
                       e.org_group AS org_group, r.sequence_index AS idx
                ORDER BY r.sequence_index
                """,
                case_id=case_id,
            )
            return [dict(record) for record in result]

    def find_immediate_loops_for_patient(self, case_id: str) -> list[dict[str, Any]]:
        """Variable-length-path-free example: consecutive PERFORMED events
        with the same activity - a query that would require a self-join on
        an ordered window in SQL, but is a direct pattern match here."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (p:Patient {case_id: $case_id})-[r1:PERFORMED]->(e1:Event),
                      (p)-[r2:PERFORMED]->(e2:Event)
                WHERE r2.sequence_index = r1.sequence_index + 1
                  AND e1.activity = e2.activity
                RETURN e1.activity AS repeated_activity, r1.sequence_index AS at_index
                ORDER BY at_index
                """,
                case_id=case_id,
            )
            return [dict(record) for record in result]

    def most_frequent_transitions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a:Activity)-[r:NEXT_ACTIVITY]->(b:Activity)
                RETURN a.name AS from_activity, b.name AS to_activity, r.count AS count
                ORDER BY r.count DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [dict(record) for record in result]
