"""Example 1 — Simple CRUD with runic.ogm.

Demonstrates:
  - Defining a Node with Field descriptors
  - Session-based create / read / update / delete
  - Repository.find_all() and session.get()
  - QueryBuilder: .where(), .order_by(), .limit(), .count(), .one()

Run against FalkorDB (embedded, no server required):
    uv run python examples/orm/01_simple_crud.py

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/01_simple_crud.py

Run against ArcadeDB (via Bolt):
    RUNIC_BACKEND=arcadedb ARCADEDB_HOST=localhost ARCADEDB_DATABASE=runic_examples \\
        uv run python examples/orm/01_simple_crud.py

Run against Apache AGE (PostgreSQL):
    RUNIC_BACKEND=age AGE_HOST=localhost AGE_DATABASE=postgres AGE_GRAPH=runic_examples \\
        AGE_USER=postgres AGE_PASSWORD=secret \\
        uv run python examples/orm/01_simple_crud.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

from runic.ogm import Field, Node, Repository, Session, select  # noqa: E402
from runic.ogm.driver import GraphDriver  # noqa: E402
from runic.ogm.driver.factory import create_driver  # noqa: E402
from runic.ogm.driver.falkordb import FalkorDBDriver  # noqa: E402


class Language(Node, labels=["Language"]):
    """ISO language — simple single-label node."""

    id: str
    title: str
    code: str = Field(unique=True)


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
                graph="example_crud",
            )
        from redislite import FalkorDB  # type: ignore[import-untyped]

        db = FalkorDB(protocol=2)
        return FalkorDBDriver(db.select_graph("example_crud"))
    if backend == "arcadedb":
        return create_driver(
            "arcadedb",
            host=os.getenv("ARCADEDB_HOST", "localhost"),
            port=int(os.getenv("ARCADEDB_PORT", "7687")),
            database=os.getenv("ARCADEDB_DATABASE", "runic_examples"),
            username=os.getenv("ARCADEDB_USERNAME", "root"),
            password=os.getenv("ARCADEDB_PASSWORD", "playwithdata"),
        )
    if backend == "age":
        return create_driver(
            "age",
            host=os.getenv("AGE_HOST", "localhost"),
            port=int(os.getenv("AGE_PORT", "5432")),
            database=os.getenv("AGE_DATABASE", "postgres"),
            graph=os.getenv("AGE_GRAPH", "runic_examples"),
            username=os.getenv("AGE_USER", "postgres"),
            password=os.getenv("AGE_PASSWORD", ""),
        )
    raise ValueError(
        f"Unknown RUNIC_BACKEND: {backend!r}. Supported: 'falkordb', 'arcadedb', 'age'"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    driver = _create_driver()

    # --- CREATE ---
    with Session(driver) as session:
        languages: list[Language] = [
            Language(id="en", title="English", code="en"),
            Language(id="de", title="German", code="de"),
            Language(id="fr", title="French", code="fr"),
        ]
        session.add_all(languages)
        session.commit()
        log.info("Created %d languages", len(languages))

    # --- READ ALL ---
    with Session(driver) as session:
        repo = Repository(session, Language)
        all_langs: list[Language] = repo.find_all()
        log.info("Total languages: %d", len(all_langs))
        for lang in all_langs:
            log.info("  %s — %s (%s)", lang.id, lang.title, lang.code)

    # --- READ ONE ---
    with Session(driver) as session:
        en: Language | None = session.get(Language, "en")
        assert en is not None
        log.info("Got by PK: %s", en.title)

    # --- UPDATE ---
    with Session(driver) as session:
        en = session.get(Language, "en")
        assert en is not None
        en.title = "English (UK)"  # _dirty = True automatically
        session.commit()
        log.info("Updated title to: %s", en.title)

    # --- DELETE ---
    with Session(driver) as session:
        fr: Language | None = session.get(Language, "fr")
        assert fr is not None
        session.delete(fr)
        session.commit()
        log.info("Deleted French")

    # Verify
    with Session(driver) as session:
        repo = Repository(session, Language)
        log.info("Languages remaining: %d", repo.count())

    # --- Pagination (Repository) ---
    with Session(driver) as session:
        repo = Repository(session, Language)
        first_page = repo.find_all(skip=0, limit=10)
        log.info("First 10 languages: %d items", len(first_page))

    # --- Query builder: filter by field ---
    with Session(driver) as session:
        results: list[Language] = session.scalars(
            select(Language).where(Language.code == "en")
        )
        log.info("QueryBuilder filter by code='en': %s", [r.title for r in results])

    # --- Query builder: count ---
    with Session(driver) as session:
        total: int = session.count(select(Language))
        log.info("QueryBuilder count: %d", total)

    # --- Query builder: one() ---
    with Session(driver) as session:
        lang: Language | None = session.scalar(
            select(Language).where(Language.code == "de")
        )
        log.info("QueryBuilder one() German: %s", lang and lang.title)

    # --- Query builder: order_by + limit ---
    with Session(driver) as session:
        ordered: list[Language] = session.scalars(
            select(Language).order_by(Language.code).limit(2)
        )
        log.info("QueryBuilder ordered codes: %s", [r.code for r in ordered])

    # --- Query builder: project() — scalar projection ---
    with Session(driver) as session:
        rows = session.all_rows(
            select(Language).order_by(Language.code).project(Language.code)
        )
        codes: list[str] = [r["n.code"] for r in rows]
        log.info("QueryBuilder scalar codes: %s", codes)

    # --- Query builder: build() — inspect generated Cypher ---
    cypher: str
    params: dict[str, Any]
    cypher, params = (
        select(Language)
        .where(Language.title.contains("German"))  # type: ignore[attr-defined]
        .build()
    )
    log.info("Generated Cypher: %s | params: %s", cypher, params)

    driver.close()


if __name__ == "__main__":
    run()
