"""Driver factory — create_driver() for backend-agnostic driver construction."""

from __future__ import annotations

from typing import Any

from runic.orm.driver import GraphDriver


def create_driver(backend: str, **kwargs: Any) -> GraphDriver:
    """Return a :class:`~runic.orm.driver.GraphDriver` for the given *backend*.

    Parameters
    ----------
    backend:
        ``"falkordb"`` or ``"arcadedb"``.
    **kwargs:
        Backend-specific keyword arguments forwarded to the driver constructor.

    Raises
    ------
    ValueError
        When *backend* is unknown.

    Examples
    --------
    FalkorDB::

        driver = create_driver(
            "falkordb", host="localhost", port=6379, graph="my_graph"
        )

    ArcadeDB::

        driver = create_driver(
            "arcadedb",
            host="localhost",
            port=7687,
            database="MyDB",
            username="root",
            password="secret",
        )
    """
    if backend == "falkordb":
        from runic.orm.driver.falkordb import create_falkordb_driver

        return create_falkordb_driver(**kwargs)

    if backend == "arcadedb":
        from runic.orm.driver.arcadedb import create_arcadedb_driver

        return create_arcadedb_driver(**kwargs)

    raise ValueError(
        f"Unknown driver backend {backend!r}. Supported: 'falkordb', 'arcadedb'."
    )
