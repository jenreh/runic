"""FalkorDB-specific transaction behaviour tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from runic.orm.driver import TransactionalGraphDriver
from runic.orm.driver.falkordb import FalkorDBDriver
from runic.orm.session.session import Session


class TestFalkordbTransactionalProtocol:
    def test_falkordb_driver_does_not_satisfy_protocol(self) -> None:
        driver = FalkorDBDriver(MagicMock())
        assert not isinstance(driver, TransactionalGraphDriver)


class TestSessionLazyBeginFalkordb:
    def test_begin_not_called_for_falkordb_driver(self) -> None:
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        falkor_driver = FalkorDBDriver(mock_graph)
        session = Session(falkor_driver)
        session.execute("MATCH (n) RETURN n", {})
        assert not hasattr(falkor_driver, "begin")
