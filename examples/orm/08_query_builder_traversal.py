"""Example 8 — Query builder: graph traversal.

Demonstrates:
  - traverse() — single-hop OPTIONAL MATCH (left-join)
  - traverse(optional=False) — required MATCH (inner-join, drops unmatched sources)
  - Multi-hop traversal: chaining traverse() calls
  - repeat() — variable-length path with *min..max quantifier
  - return_target() — select which node alias to decode
  - with_() — WITH clause for multi-stage pipelining
  - Filtering traversal targets with .where(on="alias")

Run against FalkorDB (embedded):
    uv run python examples/orm/08_query_builder_traversal.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/08_query_builder_traversal.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/08_query_builder_traversal.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.ogm import Field, Node, Relation, Session, select  # noqa: E402
from runic.ogm.driver import GraphDriver  # noqa: E402
from runic.ogm.driver.factory import create_driver  # noqa: E402
from runic.ogm.driver.falkordb import FalkorDBDriver  # noqa: E402

# ---------------------------------------------------------------------------
# Models: social graph — Person → Friend → Post
# ---------------------------------------------------------------------------


class Post(Node, labels=["Post"]):
    id: str = Field(primary_key=True)
    title: str = Field()
    tags: str = Field(default="")


class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    age: int = Field()
    active: bool = Field(default=True)

    friends: list[Any] = Relation(
        relationship="FRIEND_OF",
        direction="OUTGOING",
        target="Person",
    )
    authored: list[Post] = Relation(
        relationship="AUTHORED",
        direction="OUTGOING",
        target="Post",
    )
    reports_to: list[Any] = Relation(
        relationship="REPORTS_TO",
        direction="OUTGOING",
        target="Person",
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
                graph="example_qb_traversal",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_qb_traversal"))
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
        alice = Person(id="alice", name="Alice", age=30)
        bob = Person(id="bob", name="Bob", age=25)
        carol = Person(id="carol", name="Carol", age=35, active=False)
        dan = Person(id="dan", name="Dan", age=28)

        p1 = Post(id="post1", title="Intro to Graphs", tags="graph,database")
        p2 = Post(id="post2", title="Advanced Cypher", tags="cypher,graph")
        p3 = Post(id="post3", title="FalkorDB Tips", tags="falkordb")

        session.add_all([alice, bob, carol, dan, p1, p2, p3])
        session.commit()
        log.info("Created persons and posts")

    with Session(driver) as session:
        alice: Person | None = session.get(Person, "alice")
        bob: Person | None = session.get(Person, "bob")
        carol: Person | None = session.get(Person, "carol")
        dan: Person | None = session.get(Person, "dan")
        p1: Post | None = session.get(Post, "post1")
        p2: Post | None = session.get(Post, "post2")
        p3: Post | None = session.get(Post, "post3")
        assert all([alice, bob, carol, dan, p1, p2, p3])

        # Alice ← friends → Bob, Carol; Bob ← friends → Dan
        session.relate(alice, Person.friends, bob)
        session.relate(alice, Person.friends, carol)
        session.relate(bob, Person.friends, dan)

        # Authorship
        session.relate(alice, Person.authored, p1)
        session.relate(bob, Person.authored, p2)
        session.relate(bob, Person.authored, p3)

        # Hierarchy: dan → bob → alice (reporting chain)
        session.relate(dan, Person.reports_to, bob)
        session.relate(bob, Person.reports_to, alice)

        log.info("Created relationships")

    # --- Single-hop traverse: Alice's friends (OPTIONAL MATCH — left join) ---
    with Session(driver) as session:
        friends: list[Person] = session.scalars(
            select(Person)
            .alias("p")
            .where(Person.id == "alice")
            .traverse(Person.friends)
            .alias("f")
            .return_target("f")
        )
        log.info("Alice's friends (optional): %s", [f.name for f in friends])

    # --- Single-hop traverse: filter targets with where(on="alias") ---
    with Session(driver) as session:
        active_friends: list[Person] = session.scalars(
            select(Person)
            .alias("p")
            .where(Person.id == "alice")
            .traverse(Person.friends)
            .alias("f")
            .where(Person.active == True, on="f")  # noqa: E712
            .return_target("f")
        )
        log.info("Alice's ACTIVE friends: %s", [f.name for f in active_friends])

    # --- Required traverse (optional=False) — inner join, drops unmatched ---
    with Session(driver) as session:
        # Only persons who have at least one authored post
        authors: list[Person] = session.scalars(
            select(Person)
            .alias("p")
            .traverse(Person.authored, optional=False)
            .alias("post")
            .return_target("p")
            .distinct()
        )
        log.info(
            "Persons with at least one post (required MATCH): %s",
            [a.name for a in authors],
        )

    # --- Multi-hop: friends of friends ---
    with Session(driver) as session:
        fof: list[Person] = session.scalars(
            select(Person)
            .alias("p")
            .where(Person.id == "alice")
            .traverse(Person.friends)
            .alias("f")
            .traverse(Person.friends)
            .alias("fof")
            .return_target("fof")
        )
        log.info("Alice's friends-of-friends: %s", [p.name for p in fof])

    # --- Multi-hop with filter on intermediate node ---
    with Session(driver) as session:
        posts_via_friends: list[Post] = session.scalars(
            select(Person)
            .alias("p")
            .where(Person.id == "alice")
            .traverse(Person.friends)
            .alias("f")
            .traverse(Person.authored)
            .alias("post")
            .return_target("post")
        )
        log.info(
            "Posts authored by Alice's friends: %s",
            [pt.title for pt in posts_via_friends],
        )

    # --- repeat(): variable-length path — manager chain up to depth 3 ---
    with Session(driver) as session:
        managers: list[Person] = session.scalars(
            select(Person)
            .alias("p")
            .where(Person.id == "dan")
            .repeat(Person.reports_to, min_hops=1, max_hops=3)
            .alias("mgr")
            .return_target("mgr")
        )
        log.info(
            "Dan's managers chain (up to depth 3): %s",
            [m.name for m in managers],
        )

    # --- repeat(): unbounded (min_hops only) ---
    with Session(driver) as session:
        all_above: list[Person] = session.scalars(
            select(Person)
            .alias("p")
            .where(Person.id == "dan")
            .repeat(Person.reports_to, min_hops=1)
            .alias("above")
            .return_target("above")
        )
        log.info(
            "Dan's entire reporting chain (unbounded): %s",
            [m.name for m in all_above],
        )

    # --- with_() — multi-stage pipeline: filter, then traverse ---
    with Session(driver) as session:
        # Stage 1: find active persons; stage 2: find their posts
        posts: list[Post] = session.scalars(
            select(Person)
            .alias("p")
            .where(Person.active == True)  # noqa: E712
            .with_("p")
            .traverse(Person.authored)
            .alias("post")
            .return_target("post")
        )
        log.info(
            "Posts by active persons (with_ pipeline): %s",
            [pt.title for pt in posts],
        )

    # --- Traverse then filter the target by a field value ---
    with Session(driver) as session:
        cypher_posts: list[Post] = session.scalars(
            select(Person)
            .alias("p")
            .traverse(Person.authored)
            .alias("post")
            .where(Post.tags.contains("cypher"), on="post")  # type: ignore[attr-defined]
            .return_target("post")
        )
        log.info("Posts tagged 'cypher': %s", [pt.title for pt in cypher_posts])

    # --- build() for traversal — inspect generated Cypher ---
    cypher: str
    params: dict[str, Any]
    cypher, params = (
        select(Person)
        .alias("p")
        .where(Person.id == "alice")
        .traverse(Person.friends)
        .alias("f")
        .traverse(Person.authored)
        .alias("post")
        .return_target("post")
        .build()
    )
    log.info("Traversal Cypher:\n%s\nparams: %s", cypher, params)

    driver.close()


if __name__ == "__main__":
    run()
