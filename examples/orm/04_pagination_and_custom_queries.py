"""Example 4 — Pagination and custom Cypher queries.

Demonstrates:
  - find_all(skip=..., limit=...) — offset-based pagination
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
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.ogm import (  # noqa: E402
    Field,
    Node,
    Repository,
    Session,
    avg,
    count,
    select,
    sum_,
)
from runic.ogm.driver import GraphDriver  # noqa: E402
from runic.ogm.driver.factory import create_driver  # noqa: E402
from runic.ogm.driver.falkordb import FalkorDBDriver  # noqa: E402

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
        articles: list[Article] = [
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

    # --- Pagination: walk all items using skip/limit ---
    page_size = 10
    with Session(driver) as session:
        repo = ArticleRepository(session, Article)
        items = repo.find_all(limit=page_size)
        log.info("First page: %d items", len(items))

        # Walk all pages by incrementing skip until fewer items than page_size
        skip = 0
        total_seen = 0
        while True:
            batch = repo.find_all(skip=skip, limit=page_size)
            total_seen += len(batch)
            if len(batch) < page_size:
                break
            skip += page_size
        log.info("Walked all pages — total items seen: %d", total_seen)

    # --- Custom Cypher helpers ---
    with Session(driver) as session:
        repo = ArticleRepository(session, Article)

        alice_articles: list[Article] = repo.find_by_author("alice")
        log.info("Alice's articles: %d", len(alice_articles))

        published_count: int = repo.count_by_status("published")
        log.info("Published count: %d", published_count)

        top5: list[Article] = repo.top_by_views(5)
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
        page_0: list[Article] = session.scalars(
            select(Article)
            .where(Article.status == "published")
            .order_by(Article.id)
            .skip(0)
            .limit(page_size)
        )
        page_1: list[Article] = session.scalars(
            select(Article)
            .where(Article.status == "published")
            .order_by(Article.id)
            .skip(page_size)
            .limit(page_size)
        )
        log.info(
            "QueryBuilder page 0: %d items, page 1: %d items",
            len(page_0),
            len(page_1),
        )

    # --- Query builder: OR predicate — articles by alice or bob ---
    with Session(driver) as session:
        results: list[Article] = session.scalars(
            select(Article)
            .where((Article.author == "alice") | (Article.author == "bob"))
            .order_by(Article.views, desc=True)
            .limit(5)
        )
        log.info(
            "QueryBuilder OR top 5 by views: %s",
            [(a.author, a.views) for a in results],
        )

    # --- Query builder: in_() membership filter ---
    with Session(driver) as session:
        selected: list[Article] = session.scalars(
            select(Article).where(Article.id.in_(["alice-000", "alice-005", "bob-003"]))  # type: ignore[attr-defined]
        )
        log.info("QueryBuilder in_(): %s", [a.id for a in selected])

    # --- Query builder: count() per status ---
    with Session(driver) as session:
        pub_count: int = session.count(
            select(Article).where(Article.status == "published")
        )
        arc_count: int = session.count(
            select(Article).where(Article.status == "archived")
        )
        log.info("QueryBuilder count: published=%d archived=%d", pub_count, arc_count)

    # --- Query builder: aggregate per article ---
    with Session(driver) as session:
        rows: list[dict[str, Any]] = session.all_rows(
            select(Article)
            .alias("a")
            .aggregate(
                count("*").as_("total"),
                avg(Article.views).as_("avg_views"),
                sum_(Article.views).as_("total_views"),
                group_by="a",
            )
        )
        log.info("QueryBuilder aggregate all_rows: %d rows returned", len(rows))

    driver.close()


if __name__ == "__main__":
    run()
