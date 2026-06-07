"""Example 2 — Polymorphic location hierarchy.

Demonstrates:
  - Multi-label nodes (Location → Country, City, Restaurant)
  - primary_label for polymorphic queries
  - Repository returning a mix of subtypes from a parent-class query
  - Inherited fields (latitude/longitude on all Location subtypes)
  - QueryBuilder: .where() on subtype fields, .project(), .scalars(), compound predicates

Run against FalkorDB (embedded):
    uv run python examples/orm/02_polymorphic_locations.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/02_polymorphic_locations.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/02_polymorphic_locations.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Node, Repository, Session  # noqa: E402
from runic.orm.driver import GraphDriver  # noqa: E402
from runic.orm.driver.factory import create_driver  # noqa: E402
from runic.orm.driver.falkordb import FalkorDBDriver  # noqa: E402

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


def _create_driver() -> GraphDriver:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend == "falkordb":
        host = os.getenv("FALKORDB_HOST", "")
        if host:
            return create_driver(
                "falkordb",
                host=host,
                port=int(os.getenv("FALKORDB_PORT", "6379")),
                graph="example_locations",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_locations"))
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

    # --- Seed mixed location types ---
    with Session(driver) as session:
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
    with Session(driver) as session:
        repo = Repository(session, Location)
        all_locs: list[Location] = repo.find_all()
        log.info("All locations (%d):", len(all_locs))
        for loc in all_locs:
            log.info("  [%s] %s — %s", type(loc).__name__, loc.id, loc.title)

    # --- Query only countries ---
    with Session(driver) as session:
        repo = Repository(session, Country)
        countries: list[Country] = repo.find_all()
        log.info("Countries (%d):", len(countries))
        for c in countries:
            log.info("  %s: pop=%s, capital=%s", c.iso_code, c.population, c.capital)

    # --- Update an inherited field on a subtype ---
    with Session(driver) as session:
        france: Country | None = session.get(Country, "FR")
        assert france is not None
        france.population = 68_000_000  # type: ignore[attr-defined]
        session.commit()
        log.info("Updated France population to %d", france.population)  # type: ignore[attr-defined]

    # --- Polymorphic type resolution ---
    with Session(driver) as session:
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

    # --- QueryBuilder: query Restaurant subtype ---
    with Session(driver) as session:
        restaurants: list[Restaurant] = session.query(Restaurant).all()
        log.info("Restaurants via QueryBuilder: %d", len(restaurants))

    # --- Query builder: filter Country by population threshold ---
    with Session(driver) as session:
        large: list[Country] = (
            session.query(Country)
            .where(Country.population > 70_000_000)
            .order_by(Country.population, desc=True)
            .all()
        )
        log.info("Countries population > 70M: %s", [c.iso_code for c in large])

    # --- Query builder: compound AND predicate ---
    with Session(driver) as session:
        paris_area: list[City] = (
            session.query(City)
            .where(
                (City.latitude > 48.0)  # type: ignore[operator]
                & (City.longitude > 2.0)  # type: ignore[operator]
            )
            .all()
        )
        log.info("Cities in Paris quadrant: %s", [c.title for c in paris_area])

    # --- Query builder: project() → scalar list ---
    with Session(driver) as session:
        titles: list[str] = (
            session.query(Location)
            .order_by(Location.title)
            .project(Location.title)
            .scalars()
        )
        log.info("All location titles (projected): %s", titles)

    # --- Query builder: null check (locations without coordinates) ---
    with Session(driver) as session:
        no_coords: int = (
            session.query(Location)
            .where(Location.latitude.is_null())  # type: ignore[attr-defined]
            .count()
        )
        log.info("Locations without latitude: %d", no_coords)

    # --- Query builder: one() on specific subtype ---
    with Session(driver) as session:
        louvre: Museum | None = (
            session.query(Museum).where(Museum.id == "LOUVRE").one()
        )
        log.info("Museum one(): %s", louvre and louvre.title)

    driver.close()


if __name__ == "__main__":
    run()
