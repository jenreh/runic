"""Example 11 — Query builder: fulltext search and vector KNN search.

Demonstrates:
  - session.fulltext_search() — FalkorDB CALL db.idx.fulltext.queryNodes()
  - session.vector_search()   — FalkorDB KNN search via vecf32 distance operator
  - Combining search entry points with .where(), .order_by(), .limit()
  - IndexManager.create_indexes() for fulltext and vector index creation
  - build() — inspect generated Cypher for both search types

NOTE: Fulltext and vector search are FalkorDB-specific features.  This
      example skips entirely when RUNIC_BACKEND is not 'falkordb'.
      Fulltext/vector indexes additionally require FalkorDB v4+ (not
      the embedded redislite backend).

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/11_query_builder_search.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.migrate import IndexManager  # noqa: E402
from runic.ogm import (  # noqa: E402
    Field,
    GeoLocation,
    Node,
    Session,
    Vector,
)
from runic.ogm.driver import GraphDriver  # noqa: E402
from runic.ogm.driver.factory import create_driver  # noqa: E402
from runic.ogm.driver.falkordb import FalkorDBDriver  # noqa: E402

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Article(Node, labels=["Article"]):
    id: str = Field(primary_key=True)
    title: str = Field(index_type="FULLTEXT")
    body: str = Field(index_type="FULLTEXT")
    category: str = Field(index=True)
    published: bool = Field(default=True)
    embedding: Vector | None = Field(index_type="VECTOR", default=None)
    location: GeoLocation | None = Field(default=None)


# ---------------------------------------------------------------------------
# Connection helpers (FalkorDB only — fulltext/vector search is not available on ArcadeDB)
# ---------------------------------------------------------------------------


def _create_driver() -> GraphDriver:
    host = os.getenv("FALKORDB_HOST", "")
    if host:
        return create_driver(
            "falkordb",
            host=host,
            port=int(os.getenv("FALKORDB_PORT", "6379")),
            graph="example_qb_search",
        )
    from redislite import FalkorDB  # type: ignore[import-untyped]

    db = FalkorDB(protocol=2)
    return FalkorDBDriver(db.select_graph("example_qb_search"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend != "falkordb":
        log.warning(
            "Fulltext and vector search are FalkorDB-only features. Skipping (RUNIC_BACKEND=%s).",
            backend,
        )
        return

    driver = _create_driver()
    live_falkordb = bool(os.getenv("FALKORDB_HOST", ""))

    # --- Create indexes (requires live FalkorDB with index support) ---
    if live_falkordb:
        # IndexManager needs the raw FalkorDB graph handle
        from falkordb import FalkorDB

        _db = FalkorDB(
            host=os.getenv("FALKORDB_HOST", "localhost"),
            port=int(os.getenv("FALKORDB_PORT", "6379")),
        )
        mgr = IndexManager(_db.select_graph("example_qb_search"))
        try:
            mgr.create_indexes(Article)
            log.info("Indexes created for Article")
        except Exception as exc:
            log.warning("Index creation skipped: %s", exc)

    # --- Seed articles with embeddings ---
    with Session(driver) as session:
        articles: list[Article] = [
            Article(
                id="a1",
                title="Introduction to Graph Databases",
                body="Learn how graph databases model connected data efficiently.",
                category="database",
                published=True,
                embedding=Vector([0.1, 0.2, 0.3, 0.4]),
                location=GeoLocation(latitude=52.52, longitude=13.40),
            ),
            Article(
                id="a2",
                title="FalkorDB Performance Tuning",
                body="Best practices for high-throughput graph queries.",
                category="database",
                published=True,
                embedding=Vector([0.15, 0.25, 0.35, 0.38]),
                location=GeoLocation(latitude=48.86, longitude=2.35),
            ),
            Article(
                id="a3",
                title="Cypher Query Language Guide",
                body="A complete reference to writing Cypher queries.",
                category="tutorial",
                published=True,
                embedding=Vector([0.8, 0.1, 0.05, 0.05]),
                location=GeoLocation(latitude=51.50, longitude=-0.12),
            ),
            Article(
                id="a4",
                title="Python OGM Patterns",
                body="How ORMs simplify database access in Python applications.",
                category="python",
                published=True,
                embedding=Vector([0.6, 0.3, 0.05, 0.05]),
                location=GeoLocation(latitude=40.71, longitude=-74.00),
            ),
            Article(
                id="a5",
                title="Graph Algorithms Deep Dive",
                body="PageRank, shortest paths, and community detection in graphs.",
                category="algorithms",
                published=False,
                embedding=Vector([0.12, 0.22, 0.33, 0.33]),
            ),
        ]
        session.add_all(articles)
        session.commit()
        log.info("Created %d articles", len(articles))

    # --- build(): inspect fulltext search Cypher (no execution needed) ---
    with Session(driver) as session:
        cypher: str
        params: dict[str, Any]
        cypher, params = (
            session.fulltext_search(Article, query="graph databases")
            .where(Article.published == True)  # noqa: E712
            .limit(10)
            .build()
        )
        log.info("Fulltext Cypher:\n%s\nparams: %s", cypher, params)

    # --- build(): inspect vector search Cypher ---
    with Session(driver) as session:
        query_vec: list[float] = [0.1, 0.2, 0.3, 0.4]
        vec_cypher: str
        vec_params: dict[str, Any]
        vec_cypher, vec_params = (
            session.vector_search(
                Article,
                field=Article.embedding,
                vector=query_vec,
                k=3,
            )
            .where(Article.published == True)  # noqa: E712
            .build()
        )
        log.info("Vector search Cypher:\n%s\nparams: %s", vec_cypher, vec_params)

    # The following queries require a live FalkorDB with fulltext/vector index support.
    if not live_falkordb:
        log.info(
            "Skipping index-dependent queries (set FALKORDB_HOST for live FalkorDB)"
        )
        return

    # --- Fulltext search: basic ---
    with Session(driver) as session:
        results: list[Article] = session.fulltext_search(
            Article, query="graph databases"
        ).all()
        log.info("Fulltext 'graph databases': %s", [a.title for a in results])

    # --- Fulltext search + WHERE filter ---
    with Session(driver) as session:
        published_only: list[Article] = (
            session.fulltext_search(Article, query="graph")
            .where(Article.published == True)  # noqa: E712
            .all()
        )
        log.info(
            "Fulltext 'graph' + published=True: %s",
            [a.title for a in published_only],
        )

    # --- Fulltext search + category filter + order + limit ---
    with Session(driver) as session:
        db_articles: list[Article] = (
            session.fulltext_search(Article, query="database")
            .where(Article.category == "database")
            .order_by(Article.title)
            .limit(5)
            .all()
        )
        log.info(
            "Fulltext 'database' in category=database: %s",
            [a.title for a in db_articles],
        )

    # --- Vector KNN search: find 3 nearest to a query embedding ---
    with Session(driver) as session:
        knn_vec: list[float] = [0.1, 0.2, 0.3, 0.4]
        similar: list[Article] = session.vector_search(
            Article,
            field=Article.embedding,
            vector=knn_vec,
            k=3,
        ).all()
        log.info("Vector KNN k=3: %s", [a.title for a in similar])

    # --- Vector KNN + WHERE filter ---
    with Session(driver) as session:
        knn_vec2: list[float] = [0.1, 0.2, 0.3, 0.4]
        similar_published: list[Article] = (
            session.vector_search(
                Article,
                field=Article.embedding,
                vector=knn_vec2,
                k=5,
            )
            .where(Article.published == True)  # noqa: E712
            .all()
        )
        log.info(
            "Vector KNN k=5 + published=True: %s",
            [a.title for a in similar_published],
        )

    # --- Vector KNN with explicit limit override ---
    with Session(driver) as session:
        knn_vec3: list[float] = [0.8, 0.1, 0.05, 0.05]
        top1: list[Article] = (
            session.vector_search(
                Article,
                field=Article.embedding,
                vector=knn_vec3,
                k=10,
            )
            .limit(1)
            .all()
        )
        log.info(
            "Vector KNN k=10 LIMIT 1 (most similar): %s",
            [a.title for a in top1],
        )

    driver.close()


if __name__ == "__main__":
    run()
