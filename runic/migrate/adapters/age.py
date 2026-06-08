"""Apache AGE migration adapter.

Apache AGE stores graph data inside PostgreSQL, so migration version-tracking
nodes are created as AGE vertices (not PostgreSQL tables).  The adapter
executes Cypher through the AGE ``cypher()`` SQL function and delegates
agtype decoding to the :mod:`runic.ogm.driver.age` module.
"""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import GraphAdapterBase
from runic.ogm.driver.age import AGEDriver
from runic.ogm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)


class AGEAdapter(GraphAdapterBase, GraphAdapter):
    """Migration adapter for Apache AGE (PostgreSQL graph extension)."""

    _backend_name = "Apache AGE"
    supports_multi_label: bool = False

    def __init__(self, driver: AGEDriver, graph_name: str) -> None:
        self._driver = driver
        self._graph_name = graph_name

    @classmethod
    def from_params(
        cls,
        graph: str,
        *,
        host: str = "localhost",
        port: int = 5432,
        database: str = "postgres",
        username: str = "postgres",
        password: str = "",  # noqa: S107
    ) -> AGEAdapter:
        from runic.ogm.driver.age import create_age_driver

        driver = create_age_driver(
            host=host,
            port=port,
            database=database,
            graph=graph,
            username=username,
            password=password,
        )
        return cls(driver, graph)

    @property
    def name(self) -> str:
        return self._graph_name

    def execute(self, cypher: str, params: dict[str, Any]) -> Any:
        result = self._driver.execute(cypher, params)
        self._driver.commit()
        return result

    def run_query(self, query: str, params: dict | None = None) -> Any:
        result = self._driver.execute(query, params or {})
        # AGEDriver no longer auto-commits; the adapter owns the transaction
        # lifecycle for write operations (not managed by an OGM Session here).
        self._driver.commit()
        return result

    def run_ro_query(self, query: str) -> Any:
        return self._driver.execute(query, {})

    def fork(self, graph_name: str) -> AGEAdapter:
        """Return a new adapter targeting a different AGE graph on the same connection."""
        new_driver = AGEDriver(self._driver._conn, graph_name)  # noqa: SLF001
        return AGEAdapter(new_driver, graph_name)

    # ------------------------------------------------------------------
    # DDL — entity types (AGE creates labels implicitly on first INSERT)
    # ------------------------------------------------------------------

    def create_vertex_type(self, label: str) -> None:  # noqa: ARG002
        pass

    def create_edge_type(self, type_name: str) -> None:  # noqa: ARG002
        pass

    # ------------------------------------------------------------------
    # DDL — indexes (AGE does not expose Cypher-level DDL)
    # ------------------------------------------------------------------

    def get_existing_specs(self) -> set[IndexSpec]:
        return set()

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        log.warning(
            "AGEAdapter create_range_index: AGE does not support Cypher-level "
            "range index creation for %s.%s — create a B-tree index on the "
            "underlying PostgreSQL table manually.",
            label,
            prop,
        )

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        log.warning(
            "AGEAdapter drop_range_index: AGE does not support Cypher-level "
            "range index drops for %s.%s.",
            label,
            prop,
        )

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        log.warning(
            "AGEAdapter create_fulltext_index: AGE does not support Cypher-level "
            "fulltext index creation for %s %s — "
            "use PostgreSQL full-text search on the underlying tables.",
            label,
            props,
        )

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        log.warning(
            "AGEAdapter drop_fulltext_index: AGE does not support Cypher-level "
            "fulltext index drops for %s %s.",
            label,
            props,
        )

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,  # noqa: ARG002
        similarity: str,  # noqa: ARG002
        *,
        m: int = 16,  # noqa: ARG002
        ef_construction: int = 200,  # noqa: ARG002
        ef_runtime: int = 10,  # noqa: ARG002
    ) -> None:
        log.warning(
            "AGEAdapter create_vector_index: AGE does not support Cypher-level "
            "vector index creation for %s.%s — "
            "use pgvector on the underlying PostgreSQL tables.",
            label,
            prop,
        )

    def drop_vector_index(self, label: str, prop: str) -> None:
        log.warning(
            "AGEAdapter drop_vector_index: AGE does not support Cypher-level "
            "vector index drops for %s.%s.",
            label,
            prop,
        )

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        log.warning(
            "AGEAdapter create_constraint: AGE does not support Cypher-level "
            "constraint creation (kind=%s entity=%s label=%s props=%s) — "
            "use PostgreSQL constraints on the underlying tables.",
            kind,
            entity,
            label,
            props,
        )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        log.warning(
            "AGEAdapter drop_constraint: AGE does not support Cypher-level "
            "constraint drops (kind=%s entity=%s label=%s props=%s).",
            kind,
            entity,
            label,
            props,
        )
