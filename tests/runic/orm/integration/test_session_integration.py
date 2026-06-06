"""Integration tests for Session and Mapper using embedded FalkorDB (falkordblite).

Requires falkordblite (installed as the ``redislite`` module).
Marked with ``integration`` so they are skipped in environments without it.
"""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.driver.falkordb import FalkorDBDriver
from runic.orm.session.session import Session

try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class Language(Node, labels=["Language"]):
    id: str = Field()
    title: str = Field()
    code: str = Field(default=None)


class Tag(Node, labels=["Tag"]):
    id: int | None = Field(default=None, generated=True)
    name: str = Field()


class Location(Node, labels=["Location"], primary_label="Location"):
    id: str = Field()
    title: str = Field()


class Country(Location, labels=["Location", "Country"], primary_label="Location"):
    id: str = Field()
    iso_code: str = Field(default=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph() -> Any:
    if not _HAS_FALKORDBLITE:
        pytest.skip("falkordblite (redislite) not installed")
    db = _FalkorDB(protocol=2)
    graph_name = f"test_session_{secrets.token_hex(6)}"
    g = db.select_graph(graph_name)
    yield FalkorDBDriver(g)
    with contextlib.suppress(Exception):
        g.delete()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_and_get(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="en", title="English", code="en-US")
        s.add(lang)
        s.commit()

    with Session(graph) as s:
        loaded = s.get(Language, "en")
        assert loaded is not None
        assert loaded.id == "en"
        assert loaded.title == "English"
        assert loaded.code == "en-US"
        assert loaded._new is False


def test_update(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="fr", title="French")
        s.add(lang)
        s.commit()

    with Session(graph) as s:
        lang = s.get(Language, "fr")
        assert lang is not None
        lang.title = "Français"
        s.commit()

    with Session(graph) as s:
        lang = s.get(Language, "fr")
        assert lang is not None
        assert lang.title == "Français"


def test_delete(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="de", title="German")
        s.add(lang)
        s.commit()

    with Session(graph) as s:
        lang = s.get(Language, "de")
        assert lang is not None
        s.delete(lang)
        s.commit()

    with Session(graph) as s:
        assert s.get(Language, "de") is None


def test_generated_id_assigned_after_flush(graph: Any) -> None:
    with Session(graph) as s:
        tag = Tag(name="graph")
        s.add(tag)
        s.commit()
        assert isinstance(tag.id, int)
        assert tag.id is not None


def test_identity_map_returns_same_instance(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="es", title="Spanish")
        s.add(lang)
        s.commit()

        loaded1 = s.get(Language, "es")
        loaded2 = s.get(Language, "es")
        assert loaded1 is loaded2


def test_rollback_does_not_persist_pending(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="it", title="Italian")
        s.add(lang)
        s.rollback()

    with Session(graph) as s:
        assert s.get(Language, "it") is None


def test_refresh_reloads_entity(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="pt", title="Portuguese")
        s.add(lang)
        s.commit()

    with Session(graph) as s:
        lang = s.get(Language, "pt")
        assert lang is not None
        # Simulate external change by running a raw query
        s.execute(
            "MATCH (n:Language {id: $id}) SET n.title = $t",
            {"id": "pt", "t": "Português"},
            write=True,
        )
        s.refresh(lang)
        assert lang.title == "Português"


def test_expire_and_reload_on_refresh(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="nl", title="Dutch")
        s.add(lang)
        s.commit()

        s.expire(lang)
        assert lang.__dict__.get("_expired") is True

        s.refresh(lang)
        assert lang.__dict__.get("_expired") is not True
        assert lang.title == "Dutch"


def test_context_manager_rolls_back_on_error(graph: Any) -> None:
    try:
        with Session(graph) as s:
            lang = Language(id="ja", title="Japanese")
            s.add(lang)
            raise RuntimeError("simulated failure")
    except RuntimeError:
        pass

    with Session(graph) as s:
        assert s.get(Language, "ja") is None


def test_execute_raw_cypher(graph: Any) -> None:
    with Session(graph) as s:
        lang = Language(id="ko", title="Korean")
        s.add(lang)
        s.commit()

        result = s.execute("MATCH (n:Language {id: $id}) RETURN n.title", {"id": "ko"})
        assert result.rows
        assert result.rows[0][0] == "Korean"


def test_multiple_entities_flushed(graph: Any) -> None:
    with Session(graph) as s:
        for i in range(5):
            s.add(Language(id=f"lang{i}", title=f"Lang {i}"))
        s.commit()

    with Session(graph) as s:
        for i in range(5):
            loaded = s.get(Language, f"lang{i}")
            assert loaded is not None
            assert loaded.title == f"Lang {i}"


# ---------------------------------------------------------------------------
# Polymorphic nodes
# ---------------------------------------------------------------------------


def test_polymorphic_node_create_and_get(graph: Any) -> None:
    with Session(graph) as s:
        country = Country(id="FR", title="France", iso_code="FR")
        s.add(country)
        s.commit()

    with Session(graph) as s:
        loaded = s.get(Country, "FR")
        assert loaded is not None
        assert loaded.iso_code == "FR"
        assert isinstance(loaded, Country)
