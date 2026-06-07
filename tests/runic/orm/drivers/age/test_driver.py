"""Unit tests for AGEDriver factory, transactions, and _parse_return_columns."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from runic.orm.driver.age import AGEDriver, _parse_return_columns
from runic.orm.driver.factory import create_driver


class TestParseReturnColumns:
    def test_simple_alias(self) -> None:
        cypher = "MATCH (n:Person)\nRETURN n"
        assert _parse_return_columns(cypher) == ["n"]

    def test_multiple_aliases(self) -> None:
        cypher = (
            "MATCH (n:Person)\nOPTIONAL MATCH (n)-[:KNOWS]->(m:Person)\nRETURN n, m"
        )
        assert _parse_return_columns(cypher) == ["n", "m"]

    def test_alias_with_edge(self) -> None:
        cypher = (
            "MATCH (n:Person)\nOPTIONAL MATCH (n)-[r:KNOWS]->(m:Person)\nRETURN n, r, m"
        )
        assert _parse_return_columns(cypher) == ["n", "r", "m"]

    def test_property_projection(self) -> None:
        cypher = "MATCH (n:Person)\nRETURN n.name, n.age"
        assert _parse_return_columns(cypher) == ["name", "age"]

    def test_explicit_as_alias(self) -> None:
        cypher = "MATCH (n:Person)\nRETURN count(*) AS total"
        assert _parse_return_columns(cypher) == ["total"]

    def test_aggregation_with_group(self) -> None:
        cypher = "MATCH (n:Person)\nRETURN n, count(*) AS cnt"
        assert _parse_return_columns(cypher) == ["n", "cnt"]

    def test_distinct(self) -> None:
        cypher = "MATCH (n:Person)\nRETURN DISTINCT n"
        assert _parse_return_columns(cypher) == ["n"]

    def test_no_return_clause(self) -> None:
        cypher = "MATCH (n:Person) DETACH DELETE n"
        assert _parse_return_columns(cypher) == ["result"]

    def test_with_order_by_on_next_line(self) -> None:
        cypher = "MATCH (n:Person)\nRETURN n\nORDER BY n.name"
        assert _parse_return_columns(cypher) == ["n"]

    def test_with_limit_on_next_line(self) -> None:
        cypher = "MATCH (n:Person)\nRETURN n\nLIMIT 10"
        assert _parse_return_columns(cypher) == ["n"]


class TestCreateAgeDriver:
    def test_returns_age_driver(self) -> None:
        mock_conn = MagicMock()
        mock_psycopg = MagicMock()
        mock_psycopg.connect.return_value = mock_conn

        with (
            patch.dict(sys.modules, {"psycopg": mock_psycopg}),
            patch("runic.orm.driver.age._setup_age_connection"),
        ):
            from runic.orm.driver.age import create_age_driver

            driver = create_age_driver(
                host="localhost",
                port=5432,
                database="postgres",
                graph="test_graph",
                username="postgres",
                password="secret",
            )

        assert isinstance(driver, AGEDriver)
        assert driver._graph_name == "test_graph"

    def test_passes_connection_params(self) -> None:
        mock_conn = MagicMock()
        mock_psycopg = MagicMock()
        mock_psycopg.connect.return_value = mock_conn

        with (
            patch.dict(sys.modules, {"psycopg": mock_psycopg}),
            patch("runic.orm.driver.age._setup_age_connection"),
        ):
            from runic.orm.driver.age import create_age_driver

            create_age_driver(
                host="pg.example.com",
                port=5433,
                database="mydb",
                graph="g",
                username="alice",
                password="pw",
            )

        mock_psycopg.connect.assert_called_once_with(
            host="pg.example.com",
            port=5433,
            dbname="mydb",
            user="alice",
            password="pw",
        )


class TestCreateDriverAge:
    def test_dispatches_to_create_age_driver(self) -> None:
        with patch("runic.orm.driver.age.create_age_driver") as mock_factory:
            mock_factory.return_value = MagicMock(spec=AGEDriver)

            create_driver(
                "age",
                host="localhost",
                port=5432,
                database="postgres",
                graph="g",
                username="postgres",
                password="secret",
            )

        mock_factory.assert_called_once_with(
            host="localhost",
            port=5432,
            database="postgres",
            graph="g",
            username="postgres",
            password="secret",
        )


class TestAGEDriverTransactions:
    def test_begin_is_noop(self) -> None:
        mock_conn = MagicMock()
        driver = AGEDriver(mock_conn, "g")
        driver.begin()
        mock_conn.execute.assert_not_called()

    def test_commit_delegates_to_conn_commit(self) -> None:
        mock_conn = MagicMock()
        driver = AGEDriver(mock_conn, "g")
        driver.commit()
        mock_conn.commit.assert_called_once()

    def test_rollback_delegates_to_conn_rollback(self) -> None:
        mock_conn = MagicMock()
        driver = AGEDriver(mock_conn, "g")
        driver.rollback()
        mock_conn.rollback.assert_called_once()

    def test_execute_does_not_auto_commit(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.description = []
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        driver = AGEDriver(mock_conn, "test_graph")
        driver.execute("MATCH (n) RETURN n", {})

        mock_conn.commit.assert_not_called()

    def test_multiple_executes_without_commit_share_transaction(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.description = []
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        driver = AGEDriver(mock_conn, "test_graph")
        driver.execute("MATCH (n) RETURN n", {})
        driver.execute("MATCH (m) RETURN m", {})

        mock_conn.commit.assert_not_called()
