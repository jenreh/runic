"""Example 2 — Polymorphic location hierarchy.

Demonstrates:
  - Multi-label nodes (Location → Country, City, Restaurant)
  - primary_label for polymorphic queries
  - Repository returning a mix of subtypes from a parent-class query
  - Inherited fields (latitude/longitude on all Location subtypes)

Run:
    uv run python examples/orm/02_polymorphic_locations.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Node, Repository, Session  # noqa: E402

# ---------------------------------------------------------------------------
# Model hierarchy
# ---------------------------------------------------------------------------


class Location(Node, labels=["Location"], primary_label="Location"):
    """Polymorphic base — all location subtypes share these fields."""

    id: str
    title: str
    latitude: float | None = None
    longitude: float | None = None


class Country(Location, labels=["Location", "Country"], primary_label="Location"):
    iso_code: str
    capital: str | None = None
    population: int | None = None


class City(Location, labels=["Location", "City"], primary_label="Location"):
    population: int | None = None
    country_code: str | None = None


class Restaurant(Location, labels=["Location", "Restaurant"], primary_label="Location"):
    cuisine: str | None = None
    rating: float | None = None


class Museum(Location, labels=["Location", "Museum"], primary_label="Location"):
    opening_hours: str | None = None


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
    return db.select_graph("example_locations")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()

    # --- Seed mixed location types ---
    with Session(graph) as session:
        entities: list[Location] = [
            Country(
                id="FR",
                title="France",
                latitude=46.2,
                longitude=2.2,
                iso_code="FR",
                capital="Paris",
                population=67_000_000,
            ),
            Country(
                id="DE",
                title="Germany",
                latitude=51.2,
                longitude=10.4,
                iso_code="DE",
                capital="Berlin",
                population=83_000_000,
            ),
            City(
                id="PAR",
                title="Paris",
                latitude=48.86,
                longitude=2.35,
                population=2_000_000,
                country_code="FR",
            ),
            City(
                id="BER",
                title="Berlin",
                latitude=52.52,
                longitude=13.4,
                population=3_700_000,
                country_code="DE",
            ),
            Restaurant(
                id="JULES",
                title="Le Jules Verne",
                latitude=48.858,
                longitude=2.295,
                cuisine="French",
                rating=4.9,
            ),
            Museum(
                id="LOUVRE",
                title="Louvre Museum",
                latitude=48.861,
                longitude=2.336,
                opening_hours="Mon-Sun 09:00-18:00",
            ),
        ]
        session.add_all(entities)
        session.commit()
        log.info("Created %d location entities", len(entities))

    # --- Query all via parent class ---
    with Session(graph) as session:
        repo = Repository(session, Location)
        all_locs = repo.find_all()
        log.info("All locations (%d):", len(all_locs))
        for loc in all_locs:
            log.info("  [%s] %s — %s", type(loc).__name__, loc.id, loc.title)

    # --- Query only countries ---
    with Session(graph) as session:
        repo = Repository(session, Country)
        countries = repo.find_all()
        log.info("Countries (%d):", len(countries))
        for c in countries:
            log.info("  %s: pop=%s, capital=%s", c.iso_code, c.population, c.capital)

    # --- Update an inherited field on a subtype ---
    with Session(graph) as session:
        france = session.get(Country, "FR")
        assert france is not None
        france.population = 68_000_000  # type: ignore[attr-defined]
        session.commit()
        log.info("Updated France population to %d", france.population)  # type: ignore[attr-defined]

    # --- Polymorphic type resolution ---
    with Session(graph) as session:
        repo = Repository(session, Location)
        all_locs = repo.find_all()
        type_counts: dict[str, int] = {}
        for loc in all_locs:
            key = type(loc).__name__
            type_counts[key] = type_counts.get(key, 0) + 1
        log.info("Type distribution: %s", type_counts)
        assert type_counts.get("Country", 0) == 2
        assert type_counts.get("City", 0) == 2
        assert type_counts.get("Restaurant", 0) == 1
        assert type_counts.get("Museum", 0) == 1

    # --- Custom Cypher on parent-class repository ---
    with Session(graph) as session:
        repo_loc: Repository[Location] = Repository(session, Location)
        restaurants = repo_loc.cypher(
            "MATCH (n:Location:Restaurant) RETURN n",
            {},
            returns=Restaurant,
        )
        log.info("Restaurants via Cypher: %d", len(restaurants))


if __name__ == "__main__":
    run()
