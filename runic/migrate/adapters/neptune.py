"""Amazon Neptune migration adapter (Neptune Database and Neptune Analytics).

Neptune manages indexes automatically and exposes no Cypher-level DDL, so all
index and constraint operations are logged no-ops — the adapter's value is
version/checksum tracking via the shared ``_RunicMigrateVersion`` node and
plain-Cypher migration execution.  One adapter class serves both products;
only the underlying driver differs (Bolt for Neptune Database, the
``neptune-graph`` HTTPS API for Neptune Analytics).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import GraphAdapterBase
from runic.ogm.schema.index_manager import IndexSpec

if TYPE_CHECKING:
    from runic.ogm.driver import GraphDriver

log = logging.getLogger(__name__)


class NeptuneAdapter(GraphAdapterBase, GraphAdapter):
    """Migration adapter for Amazon Neptune (Database and Analytics)."""

    _backend_name = "Neptune"

    def __init__(self, driver: GraphDriver, graph_name: str) -> None:
        self._driver = driver
        self._graph_name = graph_name

    @classmethod
    def from_bolt_params(
        cls,
        endpoint: str,
        *,
        port: int = 8182,
        use_iam_auth: bool = True,
        region: str | None = None,
        graph_name: str = "neptune",
    ) -> NeptuneAdapter:
        """Connect to a Neptune Database cluster over Bolt."""
        from runic.ogm.driver.neptune import create_neptune_driver

        driver = create_neptune_driver(
            endpoint=endpoint,
            port=port,
            use_iam_auth=use_iam_auth,
            region=region,
        )
        return cls(driver, graph_name)

    @classmethod
    def from_analytics_params(
        cls,
        graph_id: str,
        *,
        region: str | None = None,
    ) -> NeptuneAdapter:
        """Connect to a Neptune Analytics graph via the ``neptune-graph`` API."""
        from runic.ogm.driver.neptune_analytics import create_neptune_analytics_driver

        driver = create_neptune_analytics_driver(graph_id, region=region)
        return cls(driver, graph_id)

    @property
    def name(self) -> str:
        return self._graph_name

    def execute(self, cypher: str, params: dict[str, Any]) -> Any:
        return self._driver.execute(cypher, params)

    def run_query(self, query: str, params: dict | None = None) -> Any:
        return self._driver.execute(query, params or {})

    def run_ro_query(self, query: str) -> Any:
        return self._driver.execute(query, {})

    def fork(self, graph_name: str) -> NeptuneAdapter:
        """Return a sibling adapter on the same connection.

        Neptune serves a single graph per endpoint, so the fork shares the
        driver — only the adapter's display name changes.
        """
        log.debug(
            "NeptuneAdapter fork: Neptune has one graph per endpoint; "
            "reusing the connection for %r.",
            graph_name,
        )
        return NeptuneAdapter(self._driver, graph_name)

    # ------------------------------------------------------------------
    # DDL — entity types (Neptune creates labels implicitly on first write)
    # ------------------------------------------------------------------

    def create_vertex_type(self, label: str) -> None:  # noqa: ARG002
        pass

    def create_edge_type(self, type_name: str) -> None:  # noqa: ARG002
        pass

    # ------------------------------------------------------------------
    # DDL — indexes (Neptune manages indexes automatically; no Cypher DDL)
    # ------------------------------------------------------------------

    def get_existing_specs(self) -> set[IndexSpec]:
        return set()

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        log.warning(
            "NeptuneAdapter create_range_index: Neptune manages indexes "
            "automatically — no Cypher-level index DDL for %s.%s.",
            label,
            prop,
        )

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        log.warning(
            "NeptuneAdapter drop_range_index: Neptune manages indexes "
            "automatically — no Cypher-level index DDL for %s.%s.",
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
            "NeptuneAdapter create_fulltext_index: Neptune has no Cypher-level "
            "fulltext index for %s %s — use the Amazon OpenSearch integration.",
            label,
            props,
        )

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        log.warning(
            "NeptuneAdapter drop_fulltext_index: Neptune has no Cypher-level "
            "fulltext index for %s %s.",
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
            "NeptuneAdapter create_vector_index: no Cypher-level vector index "
            "DDL for %s.%s — Neptune Analytics configures its single vector "
            "index at graph creation; Neptune Database has no vector search.",
            label,
            prop,
        )

    def drop_vector_index(self, label: str, prop: str) -> None:
        log.warning(
            "NeptuneAdapter drop_vector_index: no Cypher-level vector index "
            "DDL for %s.%s.",
            label,
            prop,
        )

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        log.warning(
            "NeptuneAdapter create_constraint: Neptune does not support "
            "Cypher-level constraints (kind=%s entity=%s label=%s props=%s).",
            kind,
            entity,
            label,
            props,
        )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        log.warning(
            "NeptuneAdapter drop_constraint: Neptune does not support "
            "Cypher-level constraints (kind=%s entity=%s label=%s props=%s).",
            kind,
            entity,
            label,
            props,
        )
