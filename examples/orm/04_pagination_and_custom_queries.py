"""Example 4 — Pagination and custom Cypher queries.

Demonstrates:
  - Pageable / Page[T] — offset-based pagination with sort
  - find_all_paginated() → page traversal
  - cypher() / cypher_one() / cypher_raw() helpers in a custom Repository
  - Raw session.execute() for write queries that don't map to a single entity

Run:
    uv run python examples/orm/04_pagination_and_custom_queries.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Field, Node, Pageable, Repository, Session  # noqa: E402

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Article(Node, labels=["Article"]):
    id: str = Field()
    title: str = Field()
    author: str = Field()
    views: int | None = Field(default=0)
    status: str = Field(default="published")


# ---------------------------------------------------------------------------
# Custom repository
# ---------------------------------------------------------------------------


class ArticleRepository(Repository[Article]):
    def find_by_author(self, author: str) -> list[Article]:
        return self.cypher(
            "MATCH (a:Article {author: $author}) RETURN a",
            {"author": author},
            returns=Article,
        )

    def count_by_status(self, status: str) -> int:
        result = self.cypher_one(
            "MATCH (a:Article {status: $status}) RETURN count(a)",
            {"status": status},
            returns=int,
        )
        return result or 0

    def top_by_views(self, limit: int = 5) -> list[Article]:
        return self.cypher(
            "MATCH (a:Article) RETURN a ORDER BY a.views DESC LIMIT $limit",
            {"limit": limit},
            returns=Article,
        )

    def bulk_archive(self, author: str) -> None:
        self.cypher(
            "MATCH (a:Article {author: $author}) SET a.status = 'archived'",
            {"author": author},
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
    return db.select_graph("example_pagination")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()

    # --- Seed 30 articles ---
    with Session(graph) as session:
        articles = [
            Article(
                id=f"alice-{i:03d}",
                title=f"Alice's Post #{i:03d}",
                author="alice",
                views=i * 100,
                status="published",
            )
            for i in range(15)
        ] + [
            Article(
                id=f"bob-{i:03d}",
                title=f"Bob's Post #{i:03d}",
                author="bob",
                views=i * 50,
                status="published",
            )
            for i in range(15)
        ]
        session.add_all(articles)
        session.commit()
        log.info("Created %d articles", len(articles))

    # --- Pagination: walk all pages ---
    with Session(graph) as session:
        repo = ArticleRepository(session, Article)
        pageable = Pageable(page=0, size=10, sort_by="id", direction="ASC")
        page = repo.find_all_paginated(pageable)
        log.info(
            "Page 0: %d items | total=%d pages=%d",
            len(list(page)),
            page.total_elements,
            page.total_pages,
        )
        log.info("has_next=%s has_prev=%s", page.has_next(), page.has_previous())

        # Walk all pages
        pageable = Pageable(page=0, size=10, sort_by="id")
        page = repo.find_all_paginated(pageable)
        total_seen = 0
        while True:
            items = list(page)
            total_seen += len(items)
            if not page.has_next():
                break
            page = repo.find_all_paginated(pageable.next())
        log.info("Walked all pages — total items seen: %d", total_seen)

    # --- Custom Cypher helpers ---
    with Session(graph) as session:
        repo = ArticleRepository(session, Article)

        alice_articles = repo.find_by_author("alice")
        log.info("Alice's articles: %d", len(alice_articles))

        published_count = repo.count_by_status("published")
        log.info("Published count: %d", published_count)

        top5 = repo.top_by_views(5)
        log.info("Top 5 by views:")
        for a in top5:
            log.info("  %s (%d views)", a.title, a.views or 0)

    # --- Bulk write via custom Cypher ---
    with Session(graph) as session:
        repo = ArticleRepository(session, Article)
        repo.bulk_archive("bob")
        archived = repo.count_by_status("archived")
        log.info("Archived Bob's articles: %d", archived)

    # --- cypher_raw: full QueryResult access ---
    with Session(graph) as session:
        repo = ArticleRepository(session, Article)
        raw = repo.cypher_raw(
            "MATCH (a:Article) RETURN a.author AS author, count(a) AS total",
            {},
        )
        header = [col[1] for col in raw.header]
        log.info("Raw result columns: %s", header)
        for row in raw.result_set:
            row_dict = dict(zip(header, row, strict=False))
            log.info("  %s", row_dict)


if __name__ == "__main__":
    run()
