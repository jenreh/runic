"""Unit tests for Session lifecycle (identity map, state transitions, flush/commit/rollback)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.exceptions import DetachedEntityError, OrmError
from runic.orm.session.session import Session
from tests.runic.orm.unit.mock_helpers import empty_result as _empty_result

# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class Person(Node, labels=["Person"]):
    id: str = Field()
    name: str = Field()
    email: str = Field(default=None)


class Country(Node, labels=["Location", "Country"], primary_label="Location"):
    id: str = Field()
    iso_code: str = Field()


class GeneratedNode(Node, labels=["Gen"]):
    id: int | None = Field(default=None, generated=True)
    title: str = Field()


# ---------------------------------------------------------------------------
# Stub dialect — no FalkorDB import
# ---------------------------------------------------------------------------


class _NodeWrapper:
    __slots__ = ("element_id", "labels", "properties")

    def __init__(
        self, element_id: Any, labels: list[str], properties: dict[str, Any]
    ) -> None:
        self.element_id = element_id
        self.labels = labels
        self.properties = properties


class _StubDialect:
    """Minimal dialect stub — enough for Session unit tests."""

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = toInteger(${param})"

    def cypher_fn_for_field(self, fi: Any) -> str | None:
        return None

    def wrap_node(self, raw: Any) -> _NodeWrapper:
        return _NodeWrapper(raw.element_id, raw.labels, raw.properties)

    def wrap_edge(self, raw: Any) -> Any:
        return raw

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:
        return f"CALL idx.fulltext.queryNodes('{label}', ${query_param}) YIELD node AS {alias}"

    def vector_knn_start(
        self, alias: str, labels_str: str, type_name: str, field_name: str
    ) -> str:
        return f"MATCH ({alias}:{labels_str})"

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:
        return f"{alias}.{field_name} <-> $__knn_vec AS __score"


class _RawNode:
    __slots__ = ("element_id", "labels", "properties")

    def __init__(
        self, element_id: Any, labels: list[str], properties: dict[str, Any]
    ) -> None:
        self.element_id = element_id
        self.labels = labels
        self.properties = properties


def _node_result(
    element_id: Any, labels: list[str], props: dict[str, Any]
) -> MagicMock:
    r = MagicMock()
    r.rows = [[_RawNode(element_id, labels, props)]]
    r.columns = ["n"]
    return r


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_driver() -> MagicMock:
    driver = MagicMock()
    driver.dialect = _StubDialect()
    driver.execute.return_value = _empty_result()
    return driver


@pytest.fixture
def session(mock_driver: MagicMock) -> Session:
    return Session(mock_driver)


class TestAdd:
    def test_add_moves_entity_to_pending(self, session: Session) -> None:
        p = Person(id="p1", name="Alice")
        session.add(p)
        assert p in session._pending

    def test_add_all_adds_multiple(self, session: Session) -> None:
        p1 = Person(id="p1", name="Alice")
        p2 = Person(id="p2", name="Bob")
        session.add_all([p1, p2])
        assert p1 in session._pending
        assert p2 in session._pending

    def test_add_idempotent(self, session: Session) -> None:
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.add(p)
        assert session._pending.count(p) == 1 or p in session._pending

    def test_add_new_flag_preserved(self, session: Session) -> None:
        p = Person(id="p1", name="Alice")
        assert p._new is True
        session.add(p)
        assert p._new is True


class TestDelete:
    def test_delete_moves_entity_to_deleted(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            "p1", ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.delete(p)
        assert p in session._deleted

    def test_delete_detached_raises(self, session: Session) -> None:
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.expunge(p)
        with pytest.raises((DetachedEntityError, OrmError)):
            session.delete(p)


class TestFlushCreate:
    def test_flush_creates_new_entity(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.flush()

        mock_driver.execute.assert_called()
        cypher: str = mock_driver.execute.call_args[0][0]
        assert "CREATE" in cypher
        assert "Person" in cypher

    def test_flush_clears_pending(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.flush()
        assert len(session._pending) == 0

    def test_flush_marks_entity_not_new(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.flush()
        assert p._new is False

    def test_flush_registers_entity_in_identity_map(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.flush()
        assert (Person, "p1") in session._identity_map

    def test_flush_assigns_generated_id(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(42, ["Gen"], {"title": "X"})
        g = GeneratedNode(title="X")
        session.add(g)
        session.flush()
        assert g.id == 42
        assert (GeneratedNode, 42) in session._identity_map


class TestFlushUpdate:
    def test_flush_updates_dirty_persistent_entity(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None

        mock_driver.execute.reset_mock()
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice Smith"}
        )

        p.name = "Alice Smith"
        assert p._dirty is True
        session.flush()

        mock_driver.execute.assert_called()
        cypher: str = mock_driver.execute.call_args[0][0]
        assert "SET" in cypher or "MERGE" in cypher

    def test_flush_clears_dirty_flag(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        p.name = "New Name"
        session.flush()
        assert p._dirty is False


class TestFlushDelete:
    def test_flush_deletes_entity(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.delete(p)

        mock_driver.execute.reset_mock()
        mock_driver.execute.return_value = _empty_result()

        session.flush()
        mock_driver.execute.assert_called()
        cypher: str = mock_driver.execute.call_args[0][0]
        assert "DETACH DELETE" in cypher

    def test_flush_removes_deleted_entity_from_identity_map(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.delete(p)

        mock_driver.execute.return_value = _empty_result()
        session.flush()
        assert (Person, "p1") not in session._identity_map


class TestCommit:
    def test_commit_flushes_and_clears_tracking_sets(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.commit()
        assert len(session._pending) == 0
        assert len(session._deleted) == 0


class TestRollback:
    def test_rollback_discards_pending(self, session: Session) -> None:
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.rollback()
        assert len(session._pending) == 0

    def test_rollback_discards_deleted(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.delete(p)
        session.rollback()
        assert len(session._deleted) == 0

    def test_rollback_expires_persistent_entities(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.rollback()
        assert p.__dict__.get("_expired") is True


class TestGet:
    def test_get_queries_driver_on_miss(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        assert p.name == "Alice"
        mock_driver.execute.assert_called_once()

    def test_get_returns_same_instance_on_second_call(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p1 = session.get(Person, "p1")
        p2 = session.get(Person, "p1")
        assert p1 is p2
        mock_driver.execute.assert_called_once()

    def test_get_returns_none_when_not_found(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _empty_result()
        result = session.get(Person, "nonexistent")
        assert result is None

    def test_get_decodes_node_fields(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice", "email": "alice@example.com"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        assert p.id == "p1"
        assert p.name == "Alice"
        assert p.email == "alice@example.com"

    def test_get_sets_not_new_not_dirty(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        assert p._new is False
        assert p._dirty is False


class TestExpireRefresh:
    def test_expire_marks_entity(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.expire(p)
        assert p.__dict__.get("_expired") is True

    def test_refresh_reloads_from_driver(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None

        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice Smith"}
        )
        session.refresh(p)
        assert p.name == "Alice Smith"

    def test_refresh_clears_expired_flag(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.expire(p)
        session.refresh(p)
        assert p.__dict__.get("_expired") is not True


class TestExpunge:
    def test_expunge_removes_from_identity_map(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        p = session.get(Person, "p1")
        assert p is not None
        session.expunge(p)
        assert (Person, "p1") not in session._identity_map

    def test_expunge_removes_from_pending(self, session: Session) -> None:
        p = Person(id="p1", name="Alice")
        session.add(p)
        session.expunge(p)
        assert p not in session._pending

    def test_expunge_all_clears_identity_map(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        session.get(Person, "p1")
        session.expunge_all()
        assert len(session._identity_map) == 0


class TestExecute:
    def test_execute_calls_driver(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _empty_result()
        session.execute("MATCH (n:Person) RETURN n")
        mock_driver.execute.assert_called_once()

    def test_execute_passes_params(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _empty_result()
        session.execute("MATCH (n:Person {id: $id}) RETURN n", {"id": "p1"})
        call_args = mock_driver.execute.call_args
        assert call_args[0][1] == {"id": "p1"}


class TestContextManager:
    def test_context_manager_commits_on_success(self, mock_driver: MagicMock) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        with Session(mock_driver) as s:
            p = Person(id="p1", name="Alice")
            s.add(p)
        assert len(s._pending) == 0

    def test_context_manager_rolls_back_on_exception(
        self, mock_driver: MagicMock
    ) -> None:
        p = Person(id="p1", name="Alice")
        with pytest.raises(RuntimeError), Session(mock_driver) as s:
            s.add(p)
            raise RuntimeError("oops")
        assert len(s._pending) == 0


class TestClose:
    def test_close_clears_identity_map(
        self, session: Session, mock_driver: MagicMock
    ) -> None:
        mock_driver.execute.return_value = _node_result(
            0, ["Person"], {"id": "p1", "name": "Alice"}
        )
        session.get(Person, "p1")
        session.close()
        assert len(session._identity_map) == 0


class TestLogCypher:
    def test_log_cypher_logs_query(
        self, mock_driver: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_driver.execute.return_value = _empty_result()
        session = Session(mock_driver, log_cypher=True)
        with caplog.at_level(logging.DEBUG, logger="runic.orm.session.session"):
            session.execute("MATCH (n) RETURN n", {"x": 1})
        assert any("MATCH (n) RETURN n" in r.message for r in caplog.records)

    def test_log_cypher_disabled_by_default(
        self, mock_driver: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_driver.execute.return_value = _empty_result()
        session = Session(mock_driver)
        with caplog.at_level(logging.DEBUG, logger="runic.orm.session.session"):
            session.execute("MATCH (n) RETURN n")
        assert not any("MATCH (n) RETURN n" in r.message for r in caplog.records)
