"""Example 4 — Pagination and custom Cypher queries.

Demonstrates:
  - Pageable / Page[T] — offset-based pagination with sort
  - find_all_paginated() → page traversal
  - cypher() / cypher_one() / cypher_raw() helpers in a custom Repository
  - Raw session.execute() for write queries that don't map to a single entity
  - QueryBuilder: .skip()/.limit() pagination, .where() with OR, aggregations via .all_rows()

Run against FalkorDB (embedded):
    uv run python examples/orm/04_pagination_and_custom_queries.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/04_pagination_and_custom_queries.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/04_pagination_and_custom_queries.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Field, Node, Pageable, Repository, Session  # noqa: E402
from runic.orm.driver import GraphDriver  # noqa: E402
from runic.orm.driver.factory import create_driver  # noqa: E402
from runic.orm.driver.falkordb import FalkorDBDriver  # noqa: E402

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


def _create_driver() -> GraphDriver:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend == "falkordb":
        host = os.getenv("FALKORDB_HOST", "")
        if host:
            return create_driver(
                "falkordb",
                host=host,
                port=int(os.getenv("FALKORDB_PORT", "6379")),
                graph="example_pagination",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_pagination"))
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

    # --- Seed 30 articles ---
    with Session(driver) as session:
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
    with Session(driver) as session:
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
            pageable = pageable.next()
            page = repo.find_all_paginated(pageable)
        log.info("Walked all pages — total items seen: %d", total_seen)

    # --- Custom Cypher helpers ---
    with Session(driver) as session:
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
    with Session(driver) as session:
        repo = ArticleRepository(session, Article)
        repo.bulk_archive("bob")
        archived = repo.count_by_status("archived")
        log.info("Archived Bob's articles: %d", archived)

    # --- cypher_raw: GraphResult access via protocol-standard .columns / .rows ---
    with Session(driver) as session:
        repo = ArticleRepository(session, Article)
        raw = repo.cypher_raw(
            "MATCH (a:Article) RETURN a.author AS author, count(a) AS total",
            {},
        )
        header = raw.columns
        log.info("Raw result columns: %s", header)
        for row in raw.rows:
            row_dict = dict(zip(header, row, strict=False))
            log.info("  %s", row_dict)

    # --- Query builder: manual skip/limit pagination ---
    with Session(driver) as session:
        page_size = 10
        page_0 = (
            session.query(Article)
            .where(Article.status == "published")
            .order_by(Article.id)
            .skip(0)
            .limit(page_size)
            .all()
        )
        page_1 = (
            session.query(Article)
            .where(Article.status == "published")
            .order_by(Article.id)
            .skip(page_size)
            .limit(page_size)
            .all()
        )
        log.info(
            "QueryBuilder page 0: %d items, page 1: %d items",
            len(page_0),
            len(page_1),
        )

    # --- Query builder: OR predicate — articles by alice or bob ---
    with Session(driver) as session:
        results = (
            session.query(Article)
            .where((Article.author == "alice") | (Article.author == "bob"))
            .order_by(Article.views, desc=True)
            .limit(5)
            .all()
        )
        log.info(
            "QueryBuilder OR top 5 by views: %s",
            [(a.author, a.views) for a in results],
        )

    # --- Query builder: in_() membership filter ---
    with Session(driver) as session:
        selected = (
            session.query(Article)
            .where(Article.id.in_(["alice-000", "alice-005", "bob-003"]))  # type: ignore[attr-defined]
            .all()
        )
        log.info("QueryBuilder in_(): %s", [a.id for a in selected])

    # --- Query builder: count() per status ---
    with Session(driver) as session:
        pub_count = session.query(Article).where(Article.status == "published").count()
        arc_count = session.query(Article).where(Article.status == "archived").count()
        log.info("QueryBuilder count: published=%d archived=%d", pub_count, arc_count)

    # --- Query builder: project() → author names only ---
    with Session(driver) as session:
        from runic.orm import avg, count, sum_

        rows = (
            session.query(Article)
            .alias("a")
            .aggregate(
                count("*").as_("total"),
                avg(Article.views).as_("avg_views"),
                sum_(Article.views).as_("total_views"),
                group_by="a",
            )
            .all_rows()
        )
        log.info("QueryBuilder aggregate all_rows: %d rows returned", len(rows))

    driver.close()


if __name__ == "__main__":
    run()
