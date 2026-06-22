"""Pytest fixtures for the runic.rag test suite.

Unit tests need only :func:`rag_settings`. Live-backend tests use
:func:`falkordb_driver`, which connects to a real FalkorDB on localhost:6379
with a random graph name and is marked ``integration``; it skips when the
server is unreachable and tears the graph down afterwards.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Iterator

import pytest

from runic.rag.config import RagSettings

__all__ = ["falkordb_driver", "rag_settings"]


@pytest.fixture
def rag_settings() -> RagSettings:
    """A small, deterministic settings object for unit tests (no network)."""
    graph = f"rag_test_{secrets.token_hex(8)}"
    return RagSettings(
        embedding_dim=16,
        backend="falkordb",
        falkordb_host="localhost",
        falkordb_port=6379,
        falkordb_graph=graph,
        openai_api_key="sk-test",
    )


@pytest.fixture
def falkordb_driver() -> Iterator[object]:
    """A live FalkorDB driver on localhost:6379 with a random graph name.

    Skips when FalkorDB is unreachable; deletes the graph on teardown.
    Tests using this fixture should be marked ``@pytest.mark.integration``.
    """
    from runic.ogm.driver.factory import create_driver

    graph = f"rag_it_{secrets.token_hex(8)}"
    try:
        driver = create_driver("falkordb", host="localhost", port=6379, graph=graph)
        driver.execute("RETURN 1", {})
    except Exception as exc:  # noqa: BLE001 - any connection failure → skip
        pytest.skip(f"FalkorDB not reachable on localhost:6379: {exc}")

    try:
        yield driver
    finally:
        try:
            # Drop the whole graph key (not just its nodes) so test graphs do
            # not accumulate as empty keys on the shared FalkorDB instance.
            _db, graph = driver.falkordb_connection()  # ty: ignore[unresolved-attribute]
            graph.delete()
        except Exception as exc:  # noqa: BLE001 - best-effort teardown
            logging.getLogger(__name__).debug("Teardown graph delete failed: %s", exc)
        close = getattr(driver, "close", None)
        if callable(close):
            close()
