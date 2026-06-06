"""Example 6 — Native FalkorDB types: Vector, GeoLocation, interned strings, auto-converters.

Demonstrates:
  - Field(interned=True)  → intern() deduplication for repeated string values
  - Vector               → vecf32() embeddings stored natively
  - GeoLocation          → point() geographic coordinates
  - Auto-converters      → datetime and Enum fields need no explicit converter=
  - QueryBuilder: filter on interned fields, Enum fields, datetime range, .in_()

NOTE: intern(), vecf32(), and point() Cypher wrappers are FalkorDB-specific.
      On ArcadeDB these fields are stored as raw Python values; round-trip
      assertions for Vector and GeoLocation may fail.

Run against FalkorDB (embedded):
    uv run python examples/orm/06_native_types.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/06_native_types.py

Run against ArcadeDB (via Bolt — native-type wrapping not applied):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/06_native_types.py
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from enum import StrEnum

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
from runic.orm.driver import GraphDriver  # noqa: E402
from runic.orm.driver.factory import create_driver  # noqa: E402
from runic.orm.driver.falkordb import FalkorDBDriver  # noqa: E402

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


def _create_driver() -> GraphDriver:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend == "falkordb":
        host = os.getenv("FALKORDB_HOST", "")
        if host:
            return create_driver(
                "falkordb",
                host=host,
                port=int(os.getenv("FALKORDB_PORT", "6379")),
                graph="example_native_types",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_native_types"))
    if backend == "arcadedb":
        log.warning(
            "Running example 06 on ArcadeDB: intern/vecf32/point wrappers are not applied; "
            "Vector and GeoLocation round-trip assertions will be skipped."
        )
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
    falkordb_backend = os.getenv("RUNIC_BACKEND", "falkordb") == "falkordb"

    # --- CREATE ---
    with Session(driver) as session:
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
    with Session(driver) as session:
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

        if falkordb_backend:
            # Vector auto-converter (vecf32 stored natively — FalkorDB only)
            assert isinstance(art.embedding, Vector)
            assert len(art.embedding) == 4
            log.info("Vector embedding[0]: %.4f", art.embedding[0])

            # GeoLocation auto-converter (point() stored natively — FalkorDB only)
            assert isinstance(art.origin, GeoLocation)
            log.info(
                "GeoLocation origin: lat=%.3f, lon=%.3f",
                art.origin.latitude,
                art.origin.longitude,
            )
        else:
            log.info(
                "Vector/GeoLocation native-type assertions skipped on non-FalkorDB backend"
            )

    # --- UPDATE — interned and typed fields in SET clause ---
    with Session(driver) as session:
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

    with Session(driver) as session:
        art = session.get(Article, "art2")
        assert art is not None
        assert art.status is ArticleStatus.PUBLISHED
        assert art.country == "Austria"
        if falkordb_backend:
            assert art.origin is not None
            assert abs(art.origin.latitude - 47.811) < 0.01
        log.info(
            "Update verified: country=%r, status=%r", art.country, art.status.value
        )

    log.info("All native-type assertions passed.")

    # --- Query builder: filter on interned string field ---
    with Session(driver) as session:
        german = session.query(Article).where(Article.country == "Germany").all()
        log.info("QueryBuilder interned country='Germany': %s", [a.id for a in german])

    # --- Query builder: filter on Enum field ---
    with Session(driver) as session:
        published = (
            session.query(Article)
            .where(Article.status == ArticleStatus.PUBLISHED)
            .order_by(Article.id)
            .all()
        )
        log.info("QueryBuilder Enum status=PUBLISHED: %s", [a.id for a in published])

    # --- Query builder: compound filter — country AND status ---
    with Session(driver) as session:
        de_published = (
            session.query(Article)
            .where(
                (Article.country == "Germany")  # type: ignore[operator]
                & (Article.status == ArticleStatus.PUBLISHED)
            )
            .all()
        )
        log.info("QueryBuilder Germany + PUBLISHED: %s", [a.id for a in de_published])

    # --- Query builder: in_() on language field ---
    with Session(driver) as session:
        multilang = (
            session.query(Article)
            .where(Article.language.in_(["en", "fr"]))  # type: ignore[attr-defined]  # noqa: E501
            .order_by(Article.id)
            .all()
        )
        log.info("QueryBuilder language in [en, fr]: %s", [a.id for a in multilang])

    # --- Query builder: not_in_() + null check ---
    with Session(driver) as session:
        without_pub_date = (
            session.query(Article)
            .where(Article.published_at.is_null())  # type: ignore[attr-defined]
            .all()
        )
        log.info(
            "QueryBuilder published_at IS NULL: %s",
            [a.id for a in without_pub_date],
        )

    driver.close()


if __name__ == "__main__":
    run()
