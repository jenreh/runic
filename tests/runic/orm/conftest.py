"""Shared fixtures for runic.orm tests."""

from collections.abc import Generator

import pytest

from runic.orm.core.metadata import metadata


@pytest.fixture(autouse=True)
def _restore_metadata() -> Generator[None]:
    """Snapshot the global metadata registry before each test and restore it after.

    Node/Edge subclasses defined at module level are registered when the module
    is imported; those persist between tests and are intentional.  This fixture
    guards against registrations made *inside* a test function leaking into
    subsequent tests.
    """
    snap = metadata.snapshot()
    yield
    metadata.restore(snap)
