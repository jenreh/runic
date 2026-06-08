"""Unit tests for ConnectionManager / AsyncConnectionManager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runic.orm.driver.falkordb import AsyncFalkorDBDriver, FalkorDBDriver
from runic.orm.session.connection_pool import (
    AsyncConnectionManager,
    ConnectionManager,
)


class TestConnectionManager:
    def test_acquire_selects_graph_and_wraps_driver(self) -> None:
        db = MagicMock()
        graph = MagicMock()
        db.select_graph.return_value = graph
        mgr = ConnectionManager(db, "g1")

        driver = mgr.acquire()

        db.select_graph.assert_called_once_with("g1")
        assert isinstance(driver, FalkorDBDriver)

    def test_graph_name_property(self) -> None:
        mgr = ConnectionManager(MagicMock(), "g1")
        assert mgr.graph_name == "g1"

    def test_release_is_noop(self) -> None:
        mgr = ConnectionManager(MagicMock(), "g1")
        # No exception, no return value.
        assert mgr.release(MagicMock()) is None


class TestAsyncConnectionManager:
    def test_acquire_selects_graph_and_wraps_driver(self) -> None:
        db = MagicMock()
        graph = MagicMock()
        db.select_graph.return_value = graph
        mgr = AsyncConnectionManager(db, "g2")

        driver = mgr.acquire()

        db.select_graph.assert_called_once_with("g2")
        assert isinstance(driver, AsyncFalkorDBDriver)

    def test_graph_name_property(self) -> None:
        mgr = AsyncConnectionManager(MagicMock(), "g2")
        assert mgr.graph_name == "g2"

    @pytest.mark.asyncio
    async def test_release_is_noop(self) -> None:
        mgr = AsyncConnectionManager(MagicMock(), "g2")
        assert await mgr.release(MagicMock()) is None
