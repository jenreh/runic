"""Unit tests for the driver factory functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
