from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from runic.orm.operations import DataOperations

if TYPE_CHECKING:
    from runic.migrate.adapters import GraphAdapter

log = logging.getLogger(__name__)


class GraphOperations(DataOperations):
    """Migration-script API: data manipulation + DDL, both with preview mode.

    Extends :class:`~runic.orm.operations.DataOperations` with DDL operations
    (indexes, constraints, snapshots) that delegate to the underlying adapter.

    Migration scripts receive this object as their ``ops`` argument::

        def upgrade(ops: GraphOperations) -> None:
            ops.create_range_index("Person", "email")
            ops.rename_property("Person", "fname", "first_name")
    """

    def __init__(self, adapter: GraphAdapter, preview: bool = False) -> None:
        super().__init__(adapter, preview=preview)
        self._adapter = adapter

    def _guard(self, preview_msg: str) -> bool:
        if self._preview:
            self._log_preview(preview_msg)
            return True
        return False

    # ------------------------------------------------------------------
    # Schema DDL — range indexes
    # ------------------------------------------------------------------

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if self._guard(f"CREATE RANGE INDEX: {label}.{prop} rel={rel}"):
            return
        self._adapter.create_range_index(label, prop, rel=rel)

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if self._guard(f"DROP RANGE INDEX: {label}.{prop} rel={rel}"):
            return
        self._adapter.drop_range_index(label, prop, rel=rel)

    # ------------------------------------------------------------------
    # Schema DDL — fulltext indexes
    # ------------------------------------------------------------------

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,
        stopwords: list[str] | None = None,
    ) -> None:
        if self._guard(
            f"CREATE FULLTEXT INDEX: {label} {list(props)} "
            f"language={language} stopwords={stopwords}"
        ):
            return
        self._adapter.create_fulltext_index(
            label, *props, language=language, stopwords=stopwords
        )

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        if self._guard(f"DROP FULLTEXT INDEX: {label} {list(props)}"):
            return
        self._adapter.drop_fulltext_index(label, *props)

    # ------------------------------------------------------------------
    # Schema DDL — vector indexes
    # ------------------------------------------------------------------

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
        if self._guard(
            f"CREATE VECTOR INDEX: {label}.{prop} dim={dimension} sim={similarity}"
        ):
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
        if self._guard(f"DROP VECTOR INDEX: {label}.{prop}"):
            return
        self._adapter.drop_vector_index(label, prop)

    # ------------------------------------------------------------------
    # Schema DDL — constraints
    # ------------------------------------------------------------------

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if self._guard(f"CREATE CONSTRAINT: {kind} {entity} {label} {props}"):
            return
        self._adapter.create_constraint(kind, entity, label, props)

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if self._guard(f"DROP CONSTRAINT: {kind} {entity} {label} {props}"):
            return
        self._adapter.drop_constraint(kind, entity, label, props)

    # ------------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------------

    def snapshot(self, snap_name: str) -> None:
        if self._guard(f"SNAPSHOT: copy {self._adapter.name} → {snap_name}"):
            return
        self._adapter.snapshot(snap_name)

    def restore_snapshot(self, snap_name: str) -> None:
        if self._guard(f"RESTORE SNAPSHOT: {snap_name} → {self._adapter.name}"):
            return
        self._adapter.restore_snapshot(snap_name)
