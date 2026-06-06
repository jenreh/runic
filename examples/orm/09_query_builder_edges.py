"""Example 9 — Query builder: edge properties and all_with_edges().

Demonstrates:
  - traverse(edge_alias="e") — named relationship variable in pattern
  - return_nodes() + return_edge() — declare columns for structured result
  - all_with_edges() — returns list[tuple[NodeA, EdgeModel, NodeB]]
  - Filtering on edge properties via .where(EdgeClass.field == val, on="e")
  - Combining node and edge filters in one query
  - build() — inspect the generated Cypher for edge queries

Run against FalkorDB (embedded):
    uv run python examples/orm/09_query_builder_edges.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/09_query_builder_edges.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/09_query_builder_edges.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Edge, Field, Node, Relation, Session  # noqa: E402
from runic.orm.driver import GraphDriver  # noqa: E402
from runic.orm.driver.factory import create_driver  # noqa: E402
from runic.orm.driver.falkordb import FalkorDBDriver  # noqa: E402

# ---------------------------------------------------------------------------
# Models: movie rating graph
# ---------------------------------------------------------------------------


class Movie(Node, labels=["Movie"]):
    id: str = Field(primary_key=True)
    title: str = Field()
    genre: str = Field()
    year: int = Field()


class Rated(Edge, type="RATED"):
    """Edge carrying the rating score and a review text."""

    score: float = Field()
    review: str | None = Field(default=None)
    recommended: bool = Field(default=False)


class Watched(Edge, type="WATCHED"):
    """Edge recording that a user has watched a movie (no score)."""

    completed: bool = Field(default=True)


class User(Node, labels=["User"]):
    id: str = Field(primary_key=True)
    name: str = Field()

    rated_movies: list[Movie] = Relation(
        relationship="RATED",
        direction="OUTGOING",
        target="Movie",
        edge_model=Rated,
    )
    watched_movies: list[Movie] = Relation(
        relationship="WATCHED",
        direction="OUTGOING",
        target="Movie",
        edge_model=Watched,
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
                graph="example_qb_edges",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_qb_edges"))
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
        alice = User(id="alice", name="Alice")
        bob = User(id="bob", name="Bob")

        inception = Movie(id="inception", title="Inception", genre="sci-fi", year=2010)
        matrix = Movie(id="matrix", title="The Matrix", genre="sci-fi", year=1999)
        godfather = Movie(
            id="godfather", title="The Godfather", genre="drama", year=1972
        )
        interstellar = Movie(
            id="interstellar", title="Interstellar", genre="sci-fi", year=2014
        )

        session.add_all([alice, bob, inception, matrix, godfather, interstellar])
        session.commit()
        log.info("Created users and movies")

    with Session(driver) as session:
        alice = session.get(User, "alice")
        bob = session.get(User, "bob")
        inception = session.get(Movie, "inception")
        matrix = session.get(Movie, "matrix")
        godfather = session.get(Movie, "godfather")
        interstellar = session.get(Movie, "interstellar")
        assert all([alice, bob, inception, matrix, godfather, interstellar])

        # Ratings
        session.relate(
            alice,
            User.rated_movies,
            inception,
            edge=Rated(score=9.5, review="Mind-bending!", recommended=True),
        )
        session.relate(
            alice,
            User.rated_movies,
            matrix,
            edge=Rated(score=8.0, review="Classic", recommended=True),
        )
        session.relate(
            alice,
            User.rated_movies,
            godfather,
            edge=Rated(score=6.5, recommended=False),
        )
        session.relate(
            bob,
            User.rated_movies,
            matrix,
            edge=Rated(score=7.5, recommended=True),
        )
        session.relate(
            bob,
            User.rated_movies,
            interstellar,
            edge=Rated(score=9.0, review="Epic", recommended=True),
        )

        # Watch history
        session.relate(
            alice, User.watched_movies, inception, edge=Watched(completed=True)
        )
        session.relate(alice, User.watched_movies, matrix, edge=Watched(completed=True))
        session.relate(
            bob, User.watched_movies, godfather, edge=Watched(completed=False)
        )

        log.info("Created rating and watch edges")

    # --- Basic all_with_edges(): (User, Rated, Movie) tuples ---
    with Session(driver) as session:
        rows = (
            session.query(User)
            .alias("u")
            .where(User.id == "alice")
            .traverse(User.rated_movies, edge_alias="r")
            .alias("m")
            .return_nodes("u", "m")
            .return_edge("r")
            .all_with_edges()
        )
        log.info("Alice's ratings:")
        for user, edge, movie in rows:
            log.info(
                "  %s rated '%s' → %.1f (recommended=%s)",
                user.name,
                movie.title,
                edge.score if edge else 0,
                edge.recommended if edge else "?",
            )

    # --- Filter on edge property: only high scores ---
    with Session(driver) as session:
        high_rated = (
            session.query(User)
            .alias("u")
            .traverse(User.rated_movies, edge_alias="r")
            .alias("m")
            .where(Rated.score >= 9.0, on="r")
            .return_nodes("u", "m")
            .return_edge("r")
            .all_with_edges()
        )
        log.info("All ratings >= 9.0:")
        for user, edge, movie in high_rated:
            log.info("  %s → '%s' (%.1f)", user.name, movie.title, edge.score)

    # --- Filter on edge property: recommended only ---
    with Session(driver) as session:
        recommended = (
            session.query(User)
            .alias("u")
            .where(User.id == "alice")
            .traverse(User.rated_movies, edge_alias="r")
            .alias("m")
            .where(Rated.recommended == True, on="r")  # noqa: E712
            .return_target("m")
            .all()
        )
        log.info("Alice's recommended movies: %s", [m.title for m in recommended])

    # --- Combine node + edge filters ---
    with Session(driver) as session:
        sci_fi_recommended = (
            session.query(User)
            .alias("u")
            .traverse(User.rated_movies, edge_alias="r")
            .alias("m")
            .where(Rated.recommended == True, on="r")  # noqa: E712
            .where(Movie.genre == "sci-fi", on="m")
            .return_nodes("u", "m")
            .return_edge("r")
            .all_with_edges()
        )
        log.info("Recommended sci-fi ratings:")
        for user, edge, movie in sci_fi_recommended:
            log.info(
                "  %s → '%s' (%d) score=%.1f",
                user.name,
                movie.title,
                movie.year,
                edge.score,
            )

    # --- return_target("m"): only movies (discard user/edge from result) ---
    with Session(driver) as session:
        bobs_movies = (
            session.query(User)
            .alias("u")
            .where(User.id == "bob")
            .traverse(User.rated_movies, edge_alias="r")
            .alias("m")
            .return_target("m")
            .all()
        )
        log.info("Bob's rated movies: %s", [m.title for m in bobs_movies])

    # --- Different edge model: Watched (required MATCH when filtering on edge) ---
    with Session(driver) as session:
        # Use optional=False (required MATCH) when filtering on traversal edge
        # properties — OPTIONAL MATCH + WHERE nullifies non-matching rows rather
        # than removing them, which would yield None movies for non-matching users.
        completed = (
            session.query(User)
            .alias("u")
            .traverse(User.watched_movies, edge_alias="w", optional=False)
            .alias("m")
            .where(Watched.completed == True, on="w")  # noqa: E712
            .return_nodes("u", "m")
            .return_edge("w")
            .all_with_edges()
        )
        log.info("Completed watches:")
        for user, edge, movie in completed:
            log.info(
                "  %s completed '%s': %s",
                user.name,
                movie.title,
                edge.completed,
            )

    # --- Filter on both edge AND node simultaneously ---
    with Session(driver) as session:
        recent_high = (
            session.query(User)
            .alias("u")
            .traverse(User.rated_movies, edge_alias="r")
            .alias("m")
            .where(Rated.score >= 8.0, on="r")
            .where(Movie.year >= 2010, on="m")
            .return_target("m")
            .order_by(Movie.year, desc=True)
            .all()
        )
        log.info(
            "High-rated (>=8) recent (>=2010) movies: %s",
            [m.title for m in recent_high],
        )

    # --- build(): inspect Cypher for edge query ---
    with Session(driver) as session:
        cypher, params = (
            session.query(User)
            .alias("u")
            .where(User.id == "alice")
            .traverse(User.rated_movies, edge_alias="r")
            .alias("m")
            .where(Rated.score >= 9.0, on="r")
            .return_nodes("u", "m")
            .return_edge("r")
            .build()
        )
        log.info("Edge query Cypher:\n%s\nparams: %s", cypher, params)

    driver.close()


if __name__ == "__main__":
    run()
