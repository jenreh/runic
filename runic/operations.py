from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runic.adapters import GraphAdapter

log = logging.getLogger(__name__)


class GraphOperations:
    def __init__(self, adapter: GraphAdapter, preview: bool = False) -> None:
        self._adapter = adapter
        self._preview = preview
        self.preview_log: list[str] = []

    def _log_preview(self, description: str) -> None:
        self.preview_log.append(description)
        log.info("[preview] %s", description)

    def run_cypher(self, query: str, params: dict | None = None) -> Any:
        if self._preview:
            self._log_preview(f"CYPHER: {query} params={params}")
            return None
        return self._adapter.run_query(query, params)

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if self._preview:
            self._log_preview(f"CREATE RANGE INDEX: {label}.{prop} rel={rel}")
            return
        self._adapter.create_range_index(label, prop, rel=rel)

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if self._preview:
            self._log_preview(f"DROP RANGE INDEX: {label}.{prop} rel={rel}")
            return
        self._adapter.drop_range_index(label, prop, rel=rel)

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if self._preview:
            self._log_preview(f"CREATE CONSTRAINT: {kind} {entity} {label} {props}")
            return
        self._adapter.create_constraint(kind, entity, label, props)

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if self._preview:
            self._log_preview(f"DROP CONSTRAINT: {kind} {entity} {label} {props}")
            return
        self._adapter.drop_constraint(kind, entity, label, props)

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,
        stopwords: list[str] | None = None,
    ) -> None:
        if self._preview:
            self._log_preview(
                f"CREATE FULLTEXT INDEX: {label} {list(props)} "
                f"language={language} stopwords={stopwords}"
            )
            return
        self._adapter.create_fulltext_index(
            label, *props, language=language, stopwords=stopwords
        )

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        if self._preview:
            self._log_preview(f"DROP FULLTEXT INDEX: {label} {list(props)}")
            return
        self._adapter.drop_fulltext_index(label, *props)

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,
        similarity: str,
        *,
        m: int = 16,
        ef_construction: int = 200,
        ef_runtime: int = 10,
    ) -> None:
        if self._preview:
            self._log_preview(
                f"CREATE VECTOR INDEX: {label}.{prop} dim={dimension} sim={similarity}"
            )
            return
        self._adapter.create_vector_index(
            label,
            prop,
            dimension,
            similarity,
            m=m,
            ef_construction=ef_construction,
            ef_runtime=ef_runtime,
        )

    def drop_vector_index(self, label: str, prop: str) -> None:
        if self._preview:
            self._log_preview(f"DROP VECTOR INDEX: {label}.{prop}")
            return
        self._adapter.drop_vector_index(label, prop)

    # ------------------------------------------------------------------
    # Data transformation ops
    # ------------------------------------------------------------------

    def rename_property(
        self, label: str, old: str, new: str, batch: int = 10_000
    ) -> None:
        if self._preview:
            self._log_preview(f"RENAME PROPERTY: {label}.{old} → {new} batch={batch}")
            return
        query = (
            f"MATCH (n:{label}) WHERE n.`{old}` IS NOT NULL AND n.`{new}` IS NULL "
            f"WITH n LIMIT $batch "
            f"SET n.`{new}` = n.`{old}` REMOVE n.`{old}` "
            f"RETURN count(n) AS affected"
        )
        log.info("renaming property %s.%s to %s", label, old, new)
        while True:
            result = self._adapter.run_query(query, {"batch": batch})
            affected = result.result_set[0][0] if result.result_set else 0
            if affected == 0:
                break

    def relabel_nodes(self, old: str, new: str, batch: int = 10_000) -> None:
        if self._preview:
            self._log_preview(f"RELABEL NODES: {old} → {new} batch={batch}")
            return
        query = (
            f"MATCH (n:{old}) WHERE NOT n:{new} "
            f"WITH n LIMIT $batch "
            f"SET n:{new} REMOVE n:{old} "
            f"RETURN count(n) AS affected"
        )
        log.info("relabelling nodes %s to %s", old, new)
        while True:
            result = self._adapter.run_query(query, {"batch": batch})
            affected = result.result_set[0][0] if result.result_set else 0
            if affected == 0:
                break

    def seed(self, merge_query: str, rows: list[dict]) -> None:
        if self._preview:
            self._log_preview(f"SEED: {len(rows)} rows via {merge_query}")
            return
        query = f"UNWIND $rows AS row {merge_query}"
        log.info("seeding %d rows", len(rows))
        self._adapter.run_query(query, {"rows": rows})

    # ------------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------------

    def snapshot(self, snap_name: str) -> None:
        if self._preview:
            self._log_preview(f"SNAPSHOT: copy {self._adapter.name} → {snap_name}")
            return
        self._adapter.snapshot(snap_name)

    def restore_snapshot(self, snap_name: str) -> None:
        if self._preview:
            self._log_preview(f"RESTORE SNAPSHOT: {snap_name} → {self._adapter.name}")
            return
        self._adapter.restore_snapshot(snap_name)
