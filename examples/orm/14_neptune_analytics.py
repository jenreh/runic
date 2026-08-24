"""Example 14 — Amazon Neptune Analytics with runic.ogm.

Demonstrates:
  - Connecting via create_driver("neptune_analytics", graph_id=...)
  - Session-based create / read / update / delete
  - Automatic vector-index sync: Neptune Analytics keeps embeddings in a
    per-graph vector index, NOT in node properties, so every Session write
    of a ``Vector`` field also upserts into that index (same statement).
    driver.upsert_vector() remains available for raw-Cypher/bulk writes,
    and sync_vectors=False opts out on graphs without a vector index.
  - Native vector KNN via vector_search()

Prerequisites:
  - A Neptune Analytics graph created WITH a vectorSearchConfiguration
    (the vector dimension is fixed at graph creation — 4 in this example).
  - AWS credentials resolvable via the standard chain, with
    ``neptune-graph:ReadDataViaQuery`` / ``WriteDataViaQuery`` permissions.
  - The ``neptune-analytics`` extra:  uv add "runic-py[neptune-analytics]"

Run:
    NEPTUNE_ANALYTICS_GRAPH_ID=g-abc123xyz AWS_REGION=eu-central-1 \\
        uv run python examples/orm/14_neptune_analytics.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.ogm import Node, Session, Vector, select, vector_search  # noqa: E402
from runic.ogm.driver.neptune_analytics import (  # noqa: E402
    NeptuneAnalyticsDriver,
    create_neptune_analytics_driver,
)

# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------


class Article(Node, labels=["Article"]):
    """A document with an embedding for similarity search."""

    id: str
    title: str
    embedding: Vector | None = None


# ---------------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------------


def _create_driver() -> NeptuneAnalyticsDriver:
    return create_neptune_analytics_driver(
        graph_id=os.environ["NEPTUNE_ANALYTICS_GRAPH_ID"],
        region=os.getenv("AWS_REGION"),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    driver = _create_driver()

    # Clean slate
    with Session(driver) as session:
        for article in session.scalars(select(Article)):
            session.delete(article)
        session.commit()

    # --- CREATE ---
    articles = [
        Article(
            id="a1", title="Graphs in Python", embedding=Vector([0.9, 0.1, 0.0, 0.0])
        ),
        Article(
            id="a2", title="Vector search 101", embedding=Vector([0.1, 0.9, 0.0, 0.0])
        ),
        Article(
            id="a3", title="Cypher deep dive", embedding=Vector([0.8, 0.2, 0.0, 0.0])
        ),
    ]
    with Session(driver) as session:
        session.add_all(articles)
        session.commit()
        # Each CREATE also ran CALL neptune.algo.vectors.upsert(n, $embedding),
        # so the articles are immediately searchable — no manual upsert needed.
        log.info("Created and indexed %d articles", len(articles))

    # --- Vector KNN ---
    with Session(driver) as session:
        hits = session.scalars(
            vector_search(Article.embedding, vector=[0.85, 0.15, 0.0, 0.0], k=2)
        )
        log.info("Nearest articles: %s", [hit.title for hit in hits])

    driver.close()


if __name__ == "__main__":
    run()
