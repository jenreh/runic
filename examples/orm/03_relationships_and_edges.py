"""Example 3 — Relationships and edge properties.

Demonstrates:
  - OUTGOING relationship from User to Trip
  - Edge model (InvitationEdge) with properties on the edge itself
  - Lazy loading (default) vs eager loading via fetch=
  - Custom repository methods for reading edge properties
  - Raw session.execute() for edge creation/reading

Run:
    uv run python examples/orm/03_relationships_and_edges.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Edge, Node, Relation, Repository, Session  # noqa: E402

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Trip(Node, labels=["Trip"]):
    id: str
    title: str
    status: str = "draft"
    destination: str | None = None


class InvitationEdge(Edge, type="INVITED_TO"):
    """Edge properties for a trip invitation."""

    role: str
    status: str
    invited_at: str  # ISO-8601
    accepted_at: str | None = None


class User(Node, labels=["User"]):
    id: str
    name: str
    email: str
    invited_trips: list[Trip] = Relation(
        relationship="INVITED_TO",
        direction="OUTGOING",
        target="Trip",
        edge_model=InvitationEdge,
    )


# ---------------------------------------------------------------------------
# Custom repository
# ---------------------------------------------------------------------------


class UserRepository(Repository[User]):
    """Typed repository with custom Cypher helpers."""

    def get_invitation(self, user_id: str, trip_id: str) -> dict | None:
        return self.cypher_one(
            """
            MATCH (u:User {id: $uid})-[e:INVITED_TO]->(t:Trip {id: $tid})
            RETURN e.role AS role, e.status AS status,
                   e.invited_at AS invited_at, e.accepted_at AS accepted_at
            """,
            {"uid": user_id, "tid": trip_id},
            returns=dict,
        )

    def find_pending_invitations(self, user_id: str) -> list[Trip]:
        return self.cypher(
            """
            MATCH (u:User {id: $uid})-[e:INVITED_TO {status: 'pending'}]->(t:Trip)
            RETURN t
            """,
            {"uid": user_id},
            returns=Trip,
        )

    def accept_invitation(self, user_id: str, trip_id: str) -> None:
        self.cypher(
            """
            MATCH (u:User {id: $uid})-[e:INVITED_TO]->(t:Trip {id: $tid})
            SET e.status = 'accepted', e.accepted_at = $accepted_at
            """,
            {
                "uid": user_id,
                "tid": trip_id,
                "accepted_at": "2026-06-05T12:00:00",
            },
            write=True,
        )


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def _connect() -> Any:
    host = os.getenv("FALKORDB_HOST", "")
    if host:
        from falkordb import FalkorDB

        db = FalkorDB(host=host, port=int(os.getenv("FALKORDB_PORT", "6379")))
    else:
        from redislite import FalkorDB  # type: ignore[no-redef]

        db = FalkorDB(protocol=2)
    return db.select_graph("example_relationships")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()

    # --- Seed ---
    with Session(graph) as session:
        users = [
            User(id="alice", name="Alice", email="alice@example.com"),
            User(id="bob", name="Bob", email="bob@example.com"),
        ]
        trips = [
            Trip(
                id="paris-2026",
                title="Paris 2026",
                status="published",
                destination="France",
            ),
            Trip(
                id="tokyo-2026",
                title="Tokyo 2026",
                status="published",
                destination="Japan",
            ),
            Trip(id="draft-trip", title="Draft Trip", status="draft"),
        ]
        session.add_all(users + trips)
        session.commit()
        log.info("Created %d users and %d trips", len(users), len(trips))

    # --- Create invitation edges via raw Cypher ---
    with Session(graph) as session:
        # Alice organises Paris and Tokyo; Bob is invited to Paris
        invitations = [
            ("alice", "paris-2026", "owner", "accepted", "2026-01-01T00:00:00"),
            ("alice", "tokyo-2026", "owner", "accepted", "2026-01-02T00:00:00"),
            ("bob", "paris-2026", "viewer", "pending", "2026-03-15T09:00:00"),
        ]
        for uid, tid, role, status, invited_at in invitations:
            session.execute(
                """
                MATCH (u:User {id: $uid}), (t:Trip {id: $tid})
                CREATE (u)-[:INVITED_TO {
                    role: $role, status: $status, invited_at: $invited_at
                }]->(t)
                """,
                {
                    "uid": uid,
                    "tid": tid,
                    "role": role,
                    "status": status,
                    "invited_at": invited_at,
                },
                write=True,
            )
        log.info("Created %d invitation edges", len(invitations))

    # --- Lazy loading ---
    with Session(graph) as session:
        alice = session.get(User, "alice")
        assert alice is not None
        trips_lazy = alice.invited_trips  # type: ignore[attr-defined]  # triggers query
        log.info("Alice's trips (lazy): %s", [t.title for t in trips_lazy])

    # --- Eager loading ---
    with Session(graph) as session:
        alice = session.get(User, "alice", fetch=["invited_trips"])
        assert alice is not None
        trips_eager = alice.invited_trips  # type: ignore[attr-defined]  # no extra query
        log.info("Alice's trips (eager): %s", [t.title for t in trips_eager])

    # --- Custom repository: read edge properties ---
    with Session(graph) as session:
        repo = UserRepository(session, User)

        inv = repo.get_invitation("bob", "paris-2026")
        log.info(
            "Bob's invitation: role=%s status=%s",
            inv and inv.get("role"),
            inv and inv.get("status"),
        )

        pending = repo.find_pending_invitations("bob")
        log.info("Bob's pending invitations: %d", len(pending))

        # Accept the invitation
        repo.accept_invitation("bob", "paris-2026")
        inv_after = repo.get_invitation("bob", "paris-2026")
        log.info("After accept: status=%s", inv_after and inv_after.get("status"))


if __name__ == "__main__":
    run()
