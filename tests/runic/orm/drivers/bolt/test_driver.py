"""Unit tests for BoltDriver transaction lifecycle and protocol conformance."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.driver import TransactionalGraphDriver
from runic.orm.driver.age import AGEDriver
from runic.orm.driver.bolt import BoltDriver
from runic.orm.driver.neo4j import _NEO4J_DIALECT
from runic.orm.session.session import Session

# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestTransactionalGraphDriverProtocol:
    def test_bolt_driver_satisfies_protocol(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = BoltDriver(
                "bolt://localhost:7687",
                ("neo4j", "secret"),
                "neo4j",
                _NEO4J_DIALECT,
            )
        assert isinstance(driver, TransactionalGraphDriver)

    def test_age_driver_satisfies_protocol(self) -> None:
        driver = AGEDriver(MagicMock(), "g")
        assert isinstance(driver, TransactionalGraphDriver)


# ---------------------------------------------------------------------------
# BoltDriver transaction lifecycle
# ---------------------------------------------------------------------------


def _make_bolt_driver() -> tuple[BoltDriver, MagicMock]:
    with patch("neo4j.GraphDatabase.driver") as mock_factory:
        mock_neo4j_driver = MagicMock()
        mock_factory.return_value = mock_neo4j_driver
        driver = BoltDriver(
            "bolt://localhost:7687",
            ("neo4j", "secret"),
            "neo4j",
            _NEO4J_DIALECT,
        )
    driver._neo4j_driver = mock_neo4j_driver
    return driver, mock_neo4j_driver


def _make_mock_result(columns: list[str] | None = None) -> MagicMock:
    result = MagicMock()
    result.keys.return_value = columns or ["n"]
    result.__iter__ = MagicMock(return_value=iter([]))
    return result


class TestBoltDriverBegin:
    def test_begin_opens_bolt_session_and_transaction(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session

        driver.begin()

        mock_neo4j_driver.session.assert_called_once_with(database="neo4j")
        mock_bolt_session.begin_transaction.assert_called_once()

    def test_begin_stores_session_and_tx(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = mock_tx

        driver.begin()

        assert driver._bolt_session is mock_bolt_session
        assert driver._tx is mock_tx

    def test_begin_raises_when_transaction_already_active(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_neo4j_driver.session.return_value = MagicMock()

        driver.begin()

        with pytest.raises(RuntimeError, match="transaction already active"):
            driver.begin()


class TestBoltDriverExecute:
    def test_execute_outside_transaction_opens_per_query_session(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_auto_session = MagicMock()
        mock_auto_session.__enter__ = MagicMock(return_value=mock_auto_session)
        mock_auto_session.__exit__ = MagicMock(return_value=False)
        mock_auto_session.run.return_value = _make_mock_result()
        mock_neo4j_driver.session.return_value = mock_auto_session

        driver.execute("MATCH (n) RETURN n", {})

        mock_neo4j_driver.session.assert_called_once()

    def test_execute_within_transaction_uses_tx(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = mock_tx
        mock_tx.run.return_value = _make_mock_result()

        driver.begin()
        mock_neo4j_driver.session.reset_mock()

        driver.execute("MATCH (n) RETURN n", {"x": 1})

        mock_tx.run.assert_called_once_with("MATCH (n) RETURN n", {"x": 1})
        mock_neo4j_driver.session.assert_not_called()

    def test_execute_within_transaction_returns_bolt_result(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = mock_tx

        mock_record = MagicMock()
        mock_record.values.return_value = ["Alice"]
        mock_tx.run.return_value = _make_mock_result(["name"])
        mock_tx.run.return_value.__iter__ = MagicMock(return_value=iter([mock_record]))

        driver.begin()
        result = driver.execute("MATCH (n) RETURN n.name AS name", {})

        assert result.columns == ["name"]


class TestBoltDriverCommit:
    def test_commit_calls_tx_commit_and_close(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = mock_tx

        driver.begin()
        driver.commit()

        mock_tx.commit.assert_called_once()
        mock_tx.close.assert_called_once()

    def test_commit_closes_bolt_session(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = mock_tx

        driver.begin()
        driver.commit()

        mock_bolt_session.close.assert_called_once()

    def test_commit_clears_tx_and_session_references(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = MagicMock()

        driver.begin()
        driver.commit()

        assert driver._tx is None
        assert driver._bolt_session is None

    def test_commit_is_noop_when_no_active_transaction(self) -> None:
        driver, _ = _make_bolt_driver()
        driver.commit()  # must not raise

    def test_after_commit_can_begin_new_transaction(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = MagicMock()

        driver.begin()
        driver.commit()
        driver.begin()

        assert mock_bolt_session.begin_transaction.call_count == 2


class TestBoltDriverRollback:
    def test_rollback_calls_tx_rollback_and_close(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = mock_tx

        driver.begin()
        driver.rollback()

        mock_tx.rollback.assert_called_once()
        mock_tx.close.assert_called_once()

    def test_rollback_closes_bolt_session(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = mock_tx

        driver.begin()
        driver.rollback()

        mock_bolt_session.close.assert_called_once()

    def test_rollback_clears_tx_and_session_references(self) -> None:
        driver, mock_neo4j_driver = _make_bolt_driver()
        mock_bolt_session = MagicMock()
        mock_neo4j_driver.session.return_value = mock_bolt_session
        mock_bolt_session.begin_transaction.return_value = MagicMock()

        driver.begin()
        driver.rollback()

        assert driver._tx is None
        assert driver._bolt_session is None

    def test_rollback_is_noop_when_no_active_transaction(self) -> None:
        driver, _ = _make_bolt_driver()
        driver.rollback()  # must not raise


# ---------------------------------------------------------------------------
# Session integration with transactional (Bolt) driver
# ---------------------------------------------------------------------------


class BoltWidget(Node, labels=["BoltWidget"]):
    id: str = Field()
    name: str = Field()


class _TransactionalStubDriver:
    """Proper-class stub satisfying TransactionalGraphDriver.

    Python 3.14 runtime_checkable Protocol isinstance() only checks class-level
    attributes; class-level stubs satisfy that; __init__ overrides them with
    MagicMock instances so assertion APIs work.
    """

    def begin(self) -> None: ...  # noqa: D102
    def commit(self) -> None: ...  # noqa: D102
    def rollback(self) -> None: ...  # noqa: D102

    def __init__(self) -> None:
        self.dialect = MagicMock()
        self.begin = MagicMock()  # ty: ignore[invalid-assignment]
        self.commit = MagicMock()  # ty: ignore[invalid-assignment]
        self.rollback = MagicMock()  # ty: ignore[invalid-assignment]
        self.execute = MagicMock()
        self.close = MagicMock()
        _empty = MagicMock()
        _empty.rows = []
        _empty.columns = []
        self.execute.return_value = _empty


def _make_transactional_mock_driver() -> Any:
    return _TransactionalStubDriver()


def _node_result_mock(node_id: Any, labels: list[str], props: dict) -> MagicMock:
    raw_node = MagicMock()
    raw_node.id = node_id
    raw_node.labels = labels
    raw_node.properties = props
    result = MagicMock()
    result.rows = [[raw_node]]
    result.columns = ["n"]
    return result


class TestSessionLazyBegin:
    def test_no_query_means_no_begin_called(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.commit()
        driver.begin.assert_not_called()

    def test_first_execute_triggers_lazy_begin(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.execute("MATCH (n) RETURN n", {})
        driver.begin.assert_called_once()

    def test_second_execute_does_not_begin_again(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.execute("MATCH (n) RETURN n", {})
        session.execute("MATCH (m) RETURN m", {})
        driver.begin.assert_called_once()


class TestSessionCommitWithTransactionalDriver:
    def test_commit_calls_driver_commit_after_flush(self) -> None:
        driver = _make_transactional_mock_driver()
        node_result = _node_result_mock(
            0, ["BoltWidget"], {"id": "w1", "name": "Sprocket"}
        )
        driver.execute.return_value = node_result

        session = Session(driver)
        w = BoltWidget(id="w1", name="Sprocket")
        session.add(w)
        session.commit()

        driver.begin.assert_called_once()
        driver.commit.assert_called_once()

    def test_commit_resets_in_transaction_flag(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.execute("MATCH (n) RETURN n", {})
        assert session._in_transaction is True

        session.commit()
        assert session._in_transaction is False

    def test_second_commit_can_begin_new_transaction(self) -> None:
        driver = _make_transactional_mock_driver()
        node_result = _node_result_mock(
            0, ["BoltWidget"], {"id": "w1", "name": "Sprocket"}
        )
        driver.execute.return_value = node_result

        session = Session(driver)

        w1 = BoltWidget(id="w1", name="Sprocket")
        session.add(w1)
        session.commit()
        assert driver.begin.call_count == 1
        assert driver.commit.call_count == 1

        driver.execute.return_value = _node_result_mock(
            1, ["BoltWidget"], {"id": "w2", "name": "Bolt"}
        )
        w2 = BoltWidget(id="w2", name="Bolt")
        session.add(w2)
        session.commit()
        assert driver.begin.call_count == 2
        assert driver.commit.call_count == 2

    def test_exit_without_queries_does_not_call_driver_commit(self) -> None:
        driver = _make_transactional_mock_driver()
        with Session(driver):
            pass
        driver.commit.assert_not_called()


class TestSessionRollbackWithTransactionalDriver:
    def test_rollback_calls_driver_rollback(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.execute("MATCH (n) RETURN n", {})
        session.rollback()
        driver.rollback.assert_called_once()

    def test_rollback_resets_in_transaction_flag(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.execute("MATCH (n) RETURN n", {})
        session.rollback()
        assert session._in_transaction is False

    def test_rollback_without_queries_does_not_call_driver_rollback(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.rollback()
        driver.rollback.assert_not_called()

    def test_context_manager_calls_driver_rollback_on_exception(self) -> None:
        driver = _make_transactional_mock_driver()

        with pytest.raises(RuntimeError), Session(driver) as s:
            s.execute("MATCH (n) RETURN n", {})
            raise RuntimeError("intentional failure")

        driver.rollback.assert_called_once()
        driver.commit.assert_not_called()


class TestSessionCloseWithActiveTransaction:
    def test_close_rolls_back_active_transaction(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.execute("MATCH (n) RETURN n", {})
        session.close()
        driver.rollback.assert_called_once()

    def test_close_after_commit_does_not_rollback(self) -> None:
        driver = _make_transactional_mock_driver()
        session = Session(driver)
        session.execute("MATCH (n) RETURN n", {})
        session.commit()
        session.close()
        driver.rollback.assert_not_called()
