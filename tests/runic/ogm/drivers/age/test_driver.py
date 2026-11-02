"""Unit tests for AGEDriver factory, transactions, and _parse_return_columns."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from runic.ogm.driver.age import AGEDriver, _dollar_quote, _parse_return_columns
from runic.ogm.driver.factory import create_driver


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
            patch("runic.ogm.driver.age._setup_age_connection"),
        ):
            from runic.ogm.driver.age import create_age_driver

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
            patch("runic.ogm.driver.age._setup_age_connection"),
        ):
            from runic.ogm.driver.age import create_age_driver

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
        with patch("runic.ogm.driver.age.create_age_driver") as mock_factory:
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


class TestDollarQuote:
    def test_wraps_cypher_in_matching_delimiters(self) -> None:
        quoted = _dollar_quote("MATCH (n) RETURN n")
        delimiter = quoted.split(" ", 1)[0]
        assert delimiter.startswith("$age_")
        assert delimiter.endswith("$")
        assert quoted == f"{delimiter} MATCH (n) RETURN n {delimiter}"

    def test_delimiter_is_random_per_call(self) -> None:
        assert _dollar_quote("RETURN 1") != _dollar_quote("RETURN 1")

    def test_legacy_fixed_tag_in_query_cannot_terminate_quote(self) -> None:
        cypher = "MATCH (n) SET n.`x$age_q$); DROP TABLE t; --` = 1 RETURN n"
        quoted = _dollar_quote(cypher)
        delimiter = quoted.split(" ", 1)[0]
        assert cypher.count(delimiter) == 0
        assert quoted.count(delimiter) == 2

    def test_rerolls_when_delimiter_collides(self) -> None:
        tokens = iter(["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"])
        with patch("runic.ogm.driver.age.secrets.token_hex", lambda _n: next(tokens)):
            quoted = _dollar_quote("RETURN '$age_aaaaaaaaaaaaaaaa$'")
        assert quoted.startswith("$age_bbbbbbbbbbbbbbbb$")


class TestExecuteQuoting:
    def test_execute_sends_randomised_delimiter_to_postgres(self) -> None:
        mock_conn = MagicMock()
        cursor = MagicMock()
        cursor.description = []
        cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        AGEDriver(mock_conn, "g").execute("MATCH (n) RETURN n", {"a": 1})

        sql = cursor.execute.call_args.args[0]
        assert "$age_q$" not in sql
        assert "cypher('g', $age_" in sql
