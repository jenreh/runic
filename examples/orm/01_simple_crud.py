"""Example 1 — Simple CRUD with runic.orm.

Demonstrates:
  - Defining a Node with Field descriptors
  - Session-based create / read / update / delete
  - Repository.find_all() and session.get()
  - QueryBuilder: .where(), .order_by(), .limit(), .count(), .one()

Run against a live FalkorDB:
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/01_simple_crud.py

Or against the embedded falkordb-lite (no server required):
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

from runic.orm import Field, Node, Repository, Session  # noqa: E402


class Language(Node, labels=["Language"]):
    """ISO language — simple single-label node."""

    id: str
    title: str
    code: str = Field(unique=True)


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
    return db.select_graph("example_crud")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    graph = _connect()

    # --- CREATE ---
    with Session(graph) as session:
        languages = [
            Language(id="en", title="English", code="en"),
            Language(id="de", title="German", code="de"),
            Language(id="fr", title="French", code="fr"),
        ]
        session.add_all(languages)
        session.commit()
        log.info("Created %d languages", len(languages))

    # --- READ ALL ---
    with Session(graph) as session:
        repo = Repository(session, Language)
        all_langs = repo.find_all()
        log.info("Total languages: %d", len(all_langs))
        for lang in all_langs:
            log.info("  %s — %s (%s)", lang.id, lang.title, lang.code)

    # --- READ ONE ---
    with Session(graph) as session:
        en = session.get(Language, "en")
        assert en is not None
        log.info("Got by PK: %s", en.title)

    # --- UPDATE ---
    with Session(graph) as session:
        en = session.get(Language, "en")
        assert en is not None
        en.title = "English (UK)"  # _dirty = True automatically
        session.commit()
        log.info("Updated title to: %s", en.title)

    # --- DELETE ---
    with Session(graph) as session:
        fr = session.get(Language, "fr")
        assert fr is not None
        session.delete(fr)
        session.commit()
        log.info("Deleted French")

    # Verify
    with Session(graph) as session:
        repo = Repository(session, Language)
        log.info("Languages remaining: %d", repo.count())

    # --- Pagination (Repository) ---
    with Session(graph) as session:
        repo = Repository(session, Language)
        from runic.orm import Pageable

        page = repo.find_all_paginated(Pageable(page=0, size=10, sort_by="code"))
        log.info("Page 0: %d items, %d total", len(list(page)), page.total_elements)

    # --- Query builder: filter by field ---
    with Session(graph) as session:
        results = session.query(Language).where(Language.code == "en").all()
        log.info("QueryBuilder filter by code='en': %s", [r.title for r in results])

    # --- Query builder: count ---
    with Session(graph) as session:
        total = session.query(Language).count()
        log.info("QueryBuilder count: %d", total)

    # --- Query builder: one() ---
    with Session(graph) as session:
        lang = session.query(Language).where(Language.code == "de").one()
        log.info("QueryBuilder one() German: %s", lang and lang.title)

    # --- Query builder: order_by + limit ---
    with Session(graph) as session:
        ordered = session.query(Language).order_by(Language.code).limit(2).all()
        log.info("QueryBuilder ordered codes: %s", [r.code for r in ordered])

    # --- Query builder: project() — scalar projection ---
    with Session(graph) as session:
        codes = (
            session.query(Language)
            .order_by(Language.code)
            .project(Language.code)
            .scalars()
        )
        log.info("QueryBuilder scalar codes: %s", codes)

    # --- Query builder: build() — inspect generated Cypher ---
    with Session(graph) as session:
        cypher, params = (
            session.query(Language)
            .where(Language.title.contains("German"))  # type: ignore[attr-defined]
            .build()
        )
        log.info("Generated Cypher: %s | params: %s", cypher, params)


if __name__ == "__main__":
    run()
