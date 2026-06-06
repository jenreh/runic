"""Example 6 — Native FalkorDB types: Vector, GeoLocation, interned strings, auto-converters.

Demonstrates:
  - Field(interned=True)  → intern() deduplication for repeated string values
  - Vector               → vecf32() embeddings stored natively
  - GeoLocation          → point() geographic coordinates
  - Auto-converters      → datetime and Enum fields need no explicit converter=

Run against a live FalkorDB:
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/06_native_types.py

Or against embedded falkordb-lite (no server required):
    uv run python examples/orm/06_native_types.py
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from runic.orm import (  # noqa: E402
    Field,
    GeoLocation,
    Node,
    Session,
    Vector,
)

# ---------------------------------------------------------------------------
# Enum — auto-converter assigns EnumConverter without converter= on Field
# ---------------------------------------------------------------------------


class ArticleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Model: Article — showcases all 4 features together
# ---------------------------------------------------------------------------


class Article(Node, labels=["Article"]):  # noqa: F811
    """A news article node using all four new native-type features."""

    id: str = Field(primary_key=True)

    # Interned string — high-cardinality-but-low-variety values benefit most
    country: str = Field(interned=True)
    language: str = Field(interned=True)

    # Auto-converters — no converter= required
    status: ArticleStatus  # EnumConverter auto-assigned
    published_at: datetime | None = None  # DatetimeConverter auto-assigned

    # Embedding vector — VectorConverter auto-assigned via Vector annotation
    embedding: Vector | None = None

    # Geographic location of the article's origin — GeoLocationConverter auto-assigned
    origin: GeoLocation | None = None

    title: str = "Title"  # default value via Field(default=...)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect() -> Any:
    host = os.getenv("FALKORDB_HOST", "")
    if host:
        from falkordb import FalkorDB

        db = FalkorDB(host=host, port=int(os.getenv("FALKORDB_PORT", "6379")))
    else:
        from redislite import FalkorDB  # type: ignore[no-redef]

        db = FalkorDB(protocol=2)
    return db.select_graph("example_native_types")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()

    # --- CREATE ---
    with Session(graph) as session:
        articles = [
            Article(
                id="art1",
                title="FalkorDB Graph Databases",
                country="Germany",  # stored via intern()
                language="en",  # stored via intern()
                status=ArticleStatus.PUBLISHED,  # stored as "published"
                published_at=datetime(
                    2024, 6, 1, 9, 0, tzinfo=UTC
                ),  # stored as ISO string
                embedding=Vector([0.12, 0.45, 0.78, 0.23]),  # stored via vecf32()
                origin=GeoLocation(
                    latitude=52.520, longitude=13.405
                ),  # stored via point()
            ),
            Article(
                id="art2",
                country="Germany",  # same interned value — FalkorDB deduplicates
                language="en",
                status=ArticleStatus.DRAFT,
                embedding=Vector([0.98, 0.01, 0.33, 0.67]),
                origin=GeoLocation(latitude=48.137, longitude=11.576),
            ),
            Article(
                id="art3",
                title="Requêtes graphiques",
                country="France",
                language="fr",
                status=ArticleStatus.PUBLISHED,
                published_at=datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
                embedding=Vector([0.55, 0.55, 0.55, 0.55]),
                origin=GeoLocation(latitude=48.853, longitude=2.349),
            ),
        ]
        session.add_all(articles)
        session.commit()
        log.info("Created %d articles", len(articles))

    # --- READ BACK — verify all types round-trip correctly ---
    with Session(graph) as session:
        art = session.get(Article, "art1")
        assert art is not None

        # Interned string reads back as plain str
        assert art.country == "Germany"
        assert isinstance(art.country, str)
        log.info("Interned country: %r", art.country)

        # Enum auto-converter
        assert art.status is ArticleStatus.PUBLISHED
        log.info("Enum status: %r", art.status)

        # datetime auto-converter
        assert isinstance(art.published_at, datetime)
        assert art.published_at.tzinfo is not None
        log.info("Datetime published_at: %s", art.published_at.isoformat())

        # Vector auto-converter (from Vector annotation on field)
        assert isinstance(art.embedding, Vector)
        assert len(art.embedding) == 4
        log.info("Vector embedding[0]: %.4f", art.embedding[0])

        # GeoLocation auto-converter
        assert isinstance(art.origin, GeoLocation)
        log.info(
            "GeoLocation origin: lat=%.3f, lon=%.3f",
            art.origin.latitude,
            art.origin.longitude,
        )

    # --- UPDATE — interned and typed fields in SET clause ---
    with Session(graph) as session:
        art = session.get(Article, "art2")
        assert art is not None
        art.status = ArticleStatus.PUBLISHED  # SET n.status = $status
        art.published_at = datetime(2024, 7, 1, tzinfo=UTC)
        art.country = "Austria"  # SET n.country = intern($country)
        art.embedding = Vector(
            [
                0.11,
                0.22,
                0.33,
                0.44,
            ]
        )  # SET n.embedding = vecf32($embedding)
        art.origin = GeoLocation(
            latitude=47.811, longitude=13.033
        )  # SET n.origin = point($origin)
        session.commit()
        log.info("Updated art2")

    with Session(graph) as session:
        art = session.get(Article, "art2")
        assert art is not None
        assert art.status is ArticleStatus.PUBLISHED
        assert art.country == "Austria"
        assert art.origin is not None
        assert abs(art.origin.latitude - 47.811) < 0.01
        log.info(
            "Update verified: country=%r, status=%r", art.country, art.status.value
        )

    log.info("All native-type assertions passed.")


if __name__ == "__main__":
    run()
