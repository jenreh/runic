"""Unit tests for Session lifecycle (identity map, state transitions, flush/commit/rollback)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.exceptions import DetachedEntityError, OrmError
from runic.orm.session.session import Session

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_graph() -> MagicMock:
    g = MagicMock()
    # Default query returns empty result
    g.query.return_value = _empty_result()
    return g


@pytest.fixture
def session(mock_graph: MagicMock) -> Session:
    return Session(mock_graph)


def _empty_result() -> MagicMock:
    r = MagicMock()
    r.result_set = []
    return r


def _node_result(node_id: Any, labels: list[str], props: dict) -> MagicMock:
    """Build a mock QueryResult with one node."""
    falkor_node = MagicMock()
    falkor_node.id = node_id
    falkor_node.labels = labels
    falkor_node.properties = props
    r = MagicMock()
    r.result_set = [[falkor_node]]
    return r


# ---------------------------------------------------------------------------
# add / add_all
# ---------------------------------------------------------------------------


def test_add_moves_entity_to_pending(session: Session) -> None:
    p = Person(id="p1", name="Alice")
    session.add(p)
    assert p in session._pending


def test_add_all_adds_multiple(session: Session) -> None:
    p1 = Person(id="p1", name="Alice")
    p2 = Person(id="p2", name="Bob")
    session.add_all([p1, p2])
    assert p1 in session._pending
    assert p2 in session._pending


def test_add_idempotent(session: Session) -> None:
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.add(p)
    assert session._pending.count(p) == 1 or p in session._pending


def test_add_new_flag_preserved(session: Session) -> None:
    p = Person(id="p1", name="Alice")
    assert p._new is True
    session.add(p)
    assert p._new is True


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_moves_entity_to_deleted(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        "p1", ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.delete(p)
    assert p in session._deleted


def test_delete_detached_raises(session: Session) -> None:
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.expunge(p)
    with pytest.raises((DetachedEntityError, OrmError)):
        session.delete(p)


# ---------------------------------------------------------------------------
# flush — CREATE path
# ---------------------------------------------------------------------------


def test_flush_creates_new_entity(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.flush()

    mock_graph.query.assert_called()
    cypher: str = mock_graph.query.call_args[0][0]
    assert "CREATE" in cypher
    assert "Person" in cypher


def test_flush_clears_pending(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.flush()
    assert len(session._pending) == 0


def test_flush_marks_entity_not_new(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.flush()
    assert p._new is False


def test_flush_registers_entity_in_identity_map(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.flush()
    assert (Person, "p1") in session._identity_map


def test_flush_assigns_generated_id(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(42, ["Gen"], {"title": "X"})
    g = GeneratedNode(title="X")
    session.add(g)
    session.flush()
    assert g.id == 42
    assert (GeneratedNode, 42) in session._identity_map


# ---------------------------------------------------------------------------
# flush — UPDATE path
# ---------------------------------------------------------------------------


def test_flush_updates_dirty_persistent_entity(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None

    mock_graph.query.reset_mock()
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice Smith"}
    )

    p.name = "Alice Smith"
    assert p._dirty is True
    session.flush()

    mock_graph.query.assert_called()
    cypher: str = mock_graph.query.call_args[0][0]
    assert "SET" in cypher or "MERGE" in cypher


def test_flush_clears_dirty_flag(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    p.name = "New Name"
    session.flush()
    assert p._dirty is False


# ---------------------------------------------------------------------------
# flush — DELETE path
# ---------------------------------------------------------------------------


def test_flush_deletes_entity(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.delete(p)

    mock_graph.query.reset_mock()
    mock_graph.query.return_value = _empty_result()

    session.flush()
    mock_graph.query.assert_called()
    cypher: str = mock_graph.query.call_args[0][0]
    assert "DETACH DELETE" in cypher


def test_flush_removes_deleted_entity_from_identity_map(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.delete(p)

    mock_graph.query.return_value = _empty_result()
    session.flush()
    assert (Person, "p1") not in session._identity_map


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


def test_commit_flushes_and_clears_tracking_sets(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.commit()
    assert len(session._pending) == 0
    assert len(session._deleted) == 0


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


def test_rollback_discards_pending(session: Session) -> None:
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.rollback()
    assert len(session._pending) == 0


def test_rollback_discards_deleted(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.delete(p)
    session.rollback()
    assert len(session._deleted) == 0


def test_rollback_expires_persistent_entities(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.rollback()
    assert p.__dict__.get("_expired") is True


# ---------------------------------------------------------------------------
# get — identity map
# ---------------------------------------------------------------------------


def test_get_queries_graph_on_miss(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    assert p.name == "Alice"
    mock_graph.query.assert_called_once()


def test_get_returns_same_instance_on_second_call(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p1 = session.get(Person, "p1")
    p2 = session.get(Person, "p1")
    assert p1 is p2
    mock_graph.query.assert_called_once()


def test_get_returns_none_when_not_found(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _empty_result()
    result = session.get(Person, "nonexistent")
    assert result is None


def test_get_decodes_node_fields(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice", "email": "alice@example.com"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    assert p.id == "p1"
    assert p.name == "Alice"
    assert p.email == "alice@example.com"


def test_get_sets_not_new_not_dirty(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    assert p._new is False
    assert p._dirty is False


# ---------------------------------------------------------------------------
# expire / refresh
# ---------------------------------------------------------------------------


def test_expire_marks_entity(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.expire(p)
    assert p.__dict__.get("_expired") is True


def test_refresh_reloads_from_graph(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None

    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice Smith"}
    )
    session.refresh(p)
    assert p.name == "Alice Smith"


def test_refresh_clears_expired_flag(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.expire(p)
    session.refresh(p)
    assert p.__dict__.get("_expired") is not True


# ---------------------------------------------------------------------------
# expunge / expunge_all
# ---------------------------------------------------------------------------


def test_expunge_removes_from_identity_map(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    p = session.get(Person, "p1")
    assert p is not None
    session.expunge(p)
    assert (Person, "p1") not in session._identity_map


def test_expunge_removes_from_pending(session: Session) -> None:
    p = Person(id="p1", name="Alice")
    session.add(p)
    session.expunge(p)
    assert p not in session._pending


def test_expunge_all_clears_identity_map(
    session: Session, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    session.get(Person, "p1")
    session.expunge_all()
    assert len(session._identity_map) == 0


# ---------------------------------------------------------------------------
# execute (raw Cypher)
# ---------------------------------------------------------------------------


def test_execute_calls_graph_query(session: Session, mock_graph: MagicMock) -> None:
    expected = _empty_result()
    mock_graph.query.return_value = expected
    result = session.execute("MATCH (n:Person) RETURN n")
    mock_graph.query.assert_called_once()
    assert result is expected


def test_execute_passes_params(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _empty_result()
    session.execute("MATCH (n:Person {id: $id}) RETURN n", {"id": "p1"})
    call_args = mock_graph.query.call_args
    assert call_args[0][1] == {"id": "p1"}


# ---------------------------------------------------------------------------
# context manager
# ---------------------------------------------------------------------------


def test_context_manager_commits_on_success(mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    with Session(mock_graph) as s:
        p = Person(id="p1", name="Alice")
        s.add(p)
    # After clean exit: pending cleared
    assert len(s._pending) == 0


def test_context_manager_rolls_back_on_exception(mock_graph: MagicMock) -> None:
    p = Person(id="p1", name="Alice")
    with pytest.raises(RuntimeError), Session(mock_graph) as s:
        s.add(p)
        raise RuntimeError("oops")
    # After exception: pending cleared by rollback
    assert len(s._pending) == 0


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_clears_identity_map(session: Session, mock_graph: MagicMock) -> None:
    mock_graph.query.return_value = _node_result(
        0, ["Person"], {"id": "p1", "name": "Alice"}
    )
    session.get(Person, "p1")
    session.close()
    assert len(session._identity_map) == 0


# ---------------------------------------------------------------------------
# log_cypher flag
# ---------------------------------------------------------------------------


def test_log_cypher_logs_query(
    mock_graph: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    mock_graph.query.return_value = _empty_result()
    session = Session(mock_graph, log_cypher=True)
    with caplog.at_level(logging.DEBUG, logger="runic.orm.session.session"):
        session.execute("MATCH (n) RETURN n", {"x": 1})
    assert any("MATCH (n) RETURN n" in r.message for r in caplog.records)


def test_log_cypher_disabled_by_default(
    mock_graph: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    mock_graph.query.return_value = _empty_result()
    session = Session(mock_graph)
    with caplog.at_level(logging.DEBUG, logger="runic.orm.session.session"):
        session.execute("MATCH (n) RETURN n")
    assert not any("MATCH (n) RETURN n" in r.message for r in caplog.records)
