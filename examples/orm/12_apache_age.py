"""Example 12 — Apache AGE (PostgreSQL graph extension) with runic.orm.

Demonstrates:
  - Connecting to Apache AGE via create_driver("age", ...)
  - Session-based create / read / update / delete
  - Repository.find_all() and session.get()
  - QueryBuilder: .where(), .order_by(), .limit(), .count(), .one()

Prerequisites:
  - PostgreSQL running with the Apache AGE extension installed:

      CREATE EXTENSION IF NOT EXISTS age;

  - The ``psycopg[binary]`` package (added automatically when you install
    runic with AGE support).

Run:
    AGE_HOST=localhost AGE_PORT=5432 AGE_DATABASE=postgres \\
        AGE_USER=postgres AGE_PASSWORD=secret \\
        uv run python examples/orm/12_apache_age.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Field, Node, Repository, Session  # noqa: E402
from runic.orm.driver import GraphDriver  # noqa: E402
from runic.orm.driver.factory import create_driver  # noqa: E402

# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------


class Language(Node, labels=["Language"]):
    """ISO language node."""

    id: str
    title: str
    code: str = Field(unique=True)


# ---------------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------------


def _create_driver() -> GraphDriver:
    return create_driver(
        "age",
        host=os.getenv("AGE_HOST", "localhost"),
        port=int(os.getenv("AGE_PORT", "5432")),
        database=os.getenv("AGE_DATABASE", "postgres"),
        graph=os.getenv("AGE_GRAPH", "runic_example"),
        username=os.getenv("AGE_USER", "postgres"),
        password=os.getenv("AGE_PASSWORD", ""),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    driver = _create_driver()

    # Clean slate
    with Session(driver) as session:
        session.query(Language).where(Language.id.in_(["en", "de", "fr"])).all()  # type: ignore[attr-defined]
        for lang in session.query(Language).all():
            session.delete(lang)
        session.commit()

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
        en.title = "English (UK)"
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

    # --- QueryBuilder: filter by field ---
    with Session(driver) as session:
        results: list[Language] = session.query(Language).where(Language.code == "en").all()
        log.info("QueryBuilder filter code='en': %s", [r.title for r in results])

    # --- QueryBuilder: count ---
    with Session(driver) as session:
        total: int = session.query(Language).count()
        log.info("QueryBuilder count: %d", total)

    # --- QueryBuilder: one() ---
    with Session(driver) as session:
        lang: Language | None = session.query(Language).where(Language.code == "de").one()
        log.info("QueryBuilder one() German: %s", lang and lang.title)

    # --- QueryBuilder: order_by + limit ---
    with Session(driver) as session:
        ordered: list[Language] = session.query(Language).order_by(Language.code).limit(2).all()
        log.info("QueryBuilder ordered codes: %s", [r.code for r in ordered])

    driver.close()


if __name__ == "__main__":
    run()
