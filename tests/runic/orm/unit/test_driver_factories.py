"""Unit tests for the driver factory functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from runic.orm.driver.age import AGEDriver, _parse_return_columns
from runic.orm.driver.factory import create_driver
from runic.orm.driver.falkordb import FalkorDBDriver, create_falkordb_driver


class TestCreateFalkordbDriver:
    def test_returns_falkordb_driver(self) -> None:
        mock_graph = MagicMock()
        with patch("falkordb.FalkorDB") as mock_cls:
            mock_db = mock_cls.return_value
            mock_db.select_graph.return_value = mock_graph

            driver = create_falkordb_driver(host="localhost", port=6379, graph="myapp")

        assert isinstance(driver, FalkorDBDriver)

    def test_passes_host_and_port(self) -> None:
        with patch("falkordb.FalkorDB") as mock_cls:
            mock_db = mock_cls.return_value
            mock_db.select_graph.return_value = MagicMock()

            create_falkordb_driver(host="redis.example.com", port=1234, graph="g")

        mock_cls.assert_called_once_with(host="redis.example.com", port=1234)

    def test_selects_correct_graph(self) -> None:
        with patch("falkordb.FalkorDB") as mock_cls:
            mock_db = mock_cls.return_value
            mock_db.select_graph.return_value = MagicMock()

            create_falkordb_driver(host="localhost", port=6379, graph="my_graph")

        mock_db.select_graph.assert_called_once_with("my_graph")


class TestCreateDriverFalkordb:
    def test_dispatches_to_create_falkordb_driver(self) -> None:
        with patch("runic.orm.driver.falkordb.create_falkordb_driver") as mock_factory:
            mock_factory.return_value = MagicMock(spec=FalkorDBDriver)

            create_driver("falkordb", host="localhost", port=6379, graph="myapp")

        mock_factory.assert_called_once_with(host="localhost", port=6379, graph="myapp")

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown driver backend 'bogus'"):
            create_driver("bogus")


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
        import sys

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
        import sys

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
