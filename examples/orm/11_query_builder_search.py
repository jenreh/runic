"""Example 11 — Query builder: fulltext search and vector KNN search.

Demonstrates:
  - session.fulltext_search() — FalkorDB CALL db.idx.fulltext.queryNodes()
  - session.vector_search()   — FalkorDB KNN search via vecf32 distance operator
  - Combining search entry points with .where(), .order_by(), .limit()
  - IndexManager.create_indexes() for fulltext and vector index creation
  - build() — inspect generated Cypher for both search types

NOTE: Fulltext and vector indexes require FalkorDB v4+ (not supported by
      the embedded redislite backend).  Running this example against
      falkordb-lite will log a skip message for the index-dependent queries.

Run against a live FalkorDB:
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/11_query_builder_search.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import (  # noqa: E402
    Field,
    GeoLocation,
    IndexManager,
    Node,
    Session,
    Vector,
)

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
    return db.select_graph("example_qb_search")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()
    live_falkordb = bool(os.getenv("FALKORDB_HOST", ""))

    # --- Create indexes (requires live FalkorDB) ---
    if live_falkordb:
        mgr = IndexManager(graph)
        try:
            mgr.create_indexes(Article)
            log.info("Indexes created for Article")
        except Exception as exc:
            log.warning("Index creation skipped: %s", exc)

    # --- Seed articles with embeddings ---
    with Session(graph) as session:
        articles = [
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
                title="Python ORM Patterns",
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
    with Session(graph) as session:
        cypher, params = (
            session.fulltext_search(Article, query="graph databases")
            .where(Article.published == True)  # noqa: E712
            .limit(10)
            .build()
        )
        log.info("Fulltext Cypher:\n%s\nparams: %s", cypher, params)

    # --- build(): inspect vector search Cypher ---
    with Session(graph) as session:
        query_vec = [0.1, 0.2, 0.3, 0.4]
        cypher, params = (
            session.vector_search(
                Article,
                field=Article.embedding,
                vector=query_vec,
                k=3,
            )
            .where(Article.published == True)  # noqa: E712
            .build()
        )
        log.info("Vector search Cypher:\n%s\nparams: %s", cypher, params)

    # The following queries require a live FalkorDB with indexes.
    if not live_falkordb:
        log.info(
            "Skipping index-dependent queries (set FALKORDB_HOST for live FalkorDB)"
        )
        return

    # --- Fulltext search: basic ---
    with Session(graph) as session:
        results = session.fulltext_search(Article, query="graph databases").all()
        log.info("Fulltext 'graph databases': %s", [a.title for a in results])

    # --- Fulltext search + WHERE filter ---
    with Session(graph) as session:
        published_only = (
            session.fulltext_search(Article, query="graph")
            .where(Article.published == True)  # noqa: E712
            .all()
        )
        log.info(
            "Fulltext 'graph' + published=True: %s",
            [a.title for a in published_only],
        )

    # --- Fulltext search + category filter + order + limit ---
    with Session(graph) as session:
        db_articles = (
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
    with Session(graph) as session:
        query_vec = [0.1, 0.2, 0.3, 0.4]
        similar = session.vector_search(
            Article,
            field=Article.embedding,
            vector=query_vec,
            k=3,
        ).all()
        log.info("Vector KNN k=3: %s", [a.title for a in similar])

    # --- Vector KNN + WHERE filter ---
    with Session(graph) as session:
        query_vec = [0.1, 0.2, 0.3, 0.4]
        similar_published = (
            session.vector_search(
                Article,
                field=Article.embedding,
                vector=query_vec,
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
    with Session(graph) as session:
        query_vec = [0.8, 0.1, 0.05, 0.05]
        top1 = (
            session.vector_search(
                Article,
                field=Article.embedding,
                vector=query_vec,
                k=10,
            )
            .limit(1)
            .all()
        )
        log.info(
            "Vector KNN k=10 LIMIT 1 (most similar): %s",
            [a.title for a in top1],
        )


if __name__ == "__main__":
    run()
