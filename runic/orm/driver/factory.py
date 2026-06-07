"""Driver factory — create_driver() for backend-agnostic driver construction."""

from __future__ import annotations

from typing import Any

from runic.orm.driver import GraphDriver


def create_driver(backend: str, **kwargs: Any) -> GraphDriver:
    """Return a :class:`~runic.orm.driver.GraphDriver` for the given *backend*.

    Parameters
    ----------
    backend:
        ``"falkordb"``, ``"arcadedb"``, ``"neo4j"``, ``"memgraph"``, or
        ``"age"``.
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

    Neo4j::

        driver = create_driver(
            "neo4j",
            host="localhost",
            port=7687,
            database="neo4j",
            username="neo4j",
            password="secret",
            encrypted=True,
        )

    Memgraph::

        driver = create_driver(
            "memgraph",
            host="localhost",
            port=7687,
            database="memgraph",
            username="",
            password="",
        )

    Apache AGE::

        driver = create_driver(
            "age",
            host="localhost",
            port=5432,
            database="postgres",
            graph="my_graph",
            username="postgres",
            password="secret",
        )
    """
    if backend == "falkordb":
        from runic.orm.driver.falkordb import create_falkordb_driver

        return create_falkordb_driver(**kwargs)

    if backend == "arcadedb":
        from runic.orm.driver.arcadedb import create_arcadedb_driver

        return create_arcadedb_driver(**kwargs)

    if backend == "neo4j":
        from runic.orm.driver.neo4j import create_neo4j_driver

        return create_neo4j_driver(**kwargs)

    if backend == "memgraph":
        from runic.orm.driver.memgraph import create_memgraph_driver

        return create_memgraph_driver(**kwargs)

    if backend == "age":
        from runic.orm.driver.age import create_age_driver

        return create_age_driver(**kwargs)

    raise ValueError(
        f"Unknown driver backend {backend!r}. "
        "Supported: 'falkordb', 'arcadedb', 'neo4j', 'memgraph', 'age'."
    )
