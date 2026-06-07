"""Example 3 — Relationships and edge properties.

Demonstrates:
  - OUTGOING relationship from User to Trip
  - Edge model (InvitationEdge) with properties on the edge itself
  - Lazy loading (default) vs eager loading via fetch=
  - session.relate() / session.unrelate() for mutation without raw Cypher
  - Custom repository methods for reading edge properties via QueryBuilder
  - QueryBuilder: .traverse(), .all_with_edges(), edge property filtering via .where(on=)

Run against FalkorDB (embedded):
    uv run python examples/orm/03_relationships_and_edges.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/03_relationships_and_edges.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/03_relationships_and_edges.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Edge, Node, Relation, Repository, Session  # noqa: E402
from runic.orm.driver import GraphDriver  # noqa: E402
from runic.orm.driver.factory import create_driver  # noqa: E402
from runic.orm.driver.falkordb import FalkorDBDriver  # noqa: E402

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
    """Typed repository with query-builder helpers."""

    def get_invitation(self, user_id: str, trip_id: str) -> InvitationEdge | None:
        rows: list[tuple[User, InvitationEdge, Trip]] = (
            self.query()
            .where(User.id == user_id)
            .alias("u")
            .traverse(User.invited_trips, edge_alias="e", optional=False)
            .alias("t")
            .where(Trip.id == trip_id, on="t")
            .return_nodes("u", "t")
            .return_edge("e")
            .all_with_edges()
        )
        if not rows:
            return None
        _, edge, _ = rows[0]
        return edge

    def find_pending_invitations(self, user_id: str) -> list[Trip]:
        return (
            self.query()
            .where(User.id == user_id)
            .alias("u")
            .traverse(User.invited_trips, edge_alias="e", optional=False)
            .alias("t")
            .where(InvitationEdge.status == "pending", on="e")
            .return_target("t")
            .all()
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


def _create_driver() -> GraphDriver:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend == "falkordb":
        host = os.getenv("FALKORDB_HOST", "")
        if host:
            return create_driver(
                "falkordb",
                host=host,
                port=int(os.getenv("FALKORDB_PORT", "6379")),
                graph="example_relationships",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_relationships"))
    if backend == "arcadedb":
        return create_driver(
            "arcadedb",
            host=os.getenv("ARCADEDB_HOST", "localhost"),
            port=int(os.getenv("ARCADEDB_PORT", "7687")),
            database=os.getenv("ARCADEDB_DATABASE", "runic_examples"),
            username=os.getenv("ARCADEDB_USERNAME", "root"),
            password=os.getenv("ARCADEDB_PASSWORD", "playwithdata"),
        )
    raise ValueError(
        f"Unknown RUNIC_BACKEND: {backend!r}. Supported: 'falkordb', 'arcadedb'"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    driver = _create_driver()

    # --- Seed ---
    with Session(driver) as session:
        users: list[User] = [
            User(id="alice", name="Alice", email="alice@example.com"),
            User(id="bob", name="Bob", email="bob@example.com"),
        ]
        trips: list[Trip] = [
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

    # --- Create invitation edges via session.relate() ---
    with Session(driver) as session:
        alice: User | None = session.get(User, "alice")
        bob: User | None = session.get(User, "bob")
        paris: Trip | None = session.get(Trip, "paris-2026")
        tokyo: Trip | None = session.get(Trip, "tokyo-2026")
        assert alice is not None
        assert bob is not None
        assert paris is not None
        assert tokyo is not None

        # Alice organises Paris and Tokyo; Bob is invited to Paris.
        # Pass the class-level descriptor (User.invited_trips) instead of a string
        # for IDE completion and type-checker coverage.
        session.relate(
            alice,
            User.invited_trips,
            paris,
            edge=InvitationEdge(
                role="owner", status="accepted", invited_at="2026-01-01T00:00:00"
            ),
        )
        session.relate(
            alice,
            User.invited_trips,
            tokyo,
            edge=InvitationEdge(
                role="owner", status="accepted", invited_at="2026-01-02T00:00:00"
            ),
        )
        session.relate(
            bob,
            User.invited_trips,
            paris,
            edge=InvitationEdge(
                role="viewer", status="pending", invited_at="2026-03-15T09:00:00"
            ),
        )
        log.info("Created 3 invitation edges")

    # --- Lazy loading ---
    with Session(driver) as session:
        alice = session.get(User, "alice")
        assert alice is not None
        trips_lazy: list[Trip] = alice.invited_trips  # type: ignore[attr-defined]  # triggers query
        log.info("Alice's trips (lazy): %s", [t.title for t in trips_lazy])

    # --- Eager loading ---
    with Session(driver) as session:
        alice = session.get(User, "alice", fetch=["invited_trips"])
        assert alice is not None
        trips_eager: list[Trip] = alice.invited_trips  # type: ignore[attr-defined]  # no extra query
        log.info("Alice's trips (eager): %s", [t.title for t in trips_eager])

    # --- Custom repository: read edge properties ---
    with Session(driver) as session:
        repo = UserRepository(session, User)

        inv: InvitationEdge | None = repo.get_invitation("bob", "paris-2026")
        log.info(
            "Bob's invitation: role=%s status=%s",
            inv and inv.role,
            inv and inv.status,
        )

        pending: list[Trip] = repo.find_pending_invitations("bob")
        log.info("Bob's pending invitations: %d", len(pending))

        # Accept the invitation
        repo.accept_invitation("bob", "paris-2026")
        inv_after: InvitationEdge | None = repo.get_invitation("bob", "paris-2026")
        log.info("After accept: status=%s", inv_after and inv_after.status)

    # --- Query builder: traverse User → Trip ---
    with Session(driver) as session:
        alice_trips: list[Trip] = (
            session.query(User)
            .alias("u")
            .where(User.id == "alice")
            .traverse(User.invited_trips)
            .alias("t")
            .return_target("t")
            .all()
        )
        log.info("QueryBuilder: Alice's trips: %s", [t.title for t in alice_trips])

    # --- Query builder: traverse with edge alias + filter on edge property ---
    with Session(driver) as session:
        owner_trips: list[Trip] = (
            session.query(User)
            .alias("u")
            .where(User.id == "alice")
            .traverse(User.invited_trips, edge_alias="e")
            .alias("t")
            .where(InvitationEdge.role == "owner", on="e")
            .return_target("t")
            .all()
        )
        log.info(
            "QueryBuilder: Alice owner-role trips: %s",
            [t.title for t in owner_trips],
        )

    # --- Query builder: all_with_edges() — returns (User, InvitationEdge, Trip) tuples ---
    with Session(driver) as session:
        rows: list[tuple[User, InvitationEdge, Trip]] = (
            session.query(User)
            .alias("u")
            .where(User.id == "alice")
            .traverse(User.invited_trips, edge_alias="e")
            .alias("t")
            .return_nodes("u", "t")
            .return_edge("e")
            .all_with_edges()
        )
        for user, edge, trip in rows:
            user: User
            edge: InvitationEdge
            trip: Trip
            log.info(
                "QueryBuilder all_with_edges: %s -[%s]-> %s",
                user.name,
                edge.role if edge else "?",
                trip.title,
            )

    driver.close()


if __name__ == "__main__":
    run()
