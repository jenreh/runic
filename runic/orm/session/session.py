"""Session: unit-of-work manager for FalkorDB graph writes."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any

from runic.orm.core.metadata import metadata as _global_metadata
from runic.orm.exceptions import DetachedEntityError, EntityNotFoundError
from runic.orm.mapper.mapper import Mapper

log = logging.getLogger(__name__)


class Session:
    """Sync unit-of-work manager.

    Owns all mutations (``add``, ``delete``), single-entity lookup (``get``),
    identity map, and flush/commit lifecycle.  Repositories hold a session
    reference and delegate writes and PK lookups to it.

    FalkorDB transaction model: single ``GRAPH.QUERY`` is fully atomic.
    Multi-query uses sequential individual queries (no native pipeline in
    the Python client).  ``rollback()`` discards un-flushed pending/deleted
    sets only; cannot undo writes already sent to the graph.
    """

    def __init__(self, graph: Any, mapper: Mapper | None = None) -> None:
        self._graph = graph
        self._mapper: Mapper = (
            mapper if mapper is not None else Mapper(_global_metadata)
        )
        # Identity map: (EntityClass, pk) → entity instance
        self._identity_map: dict[tuple[type, Any], Any] = {}
        # Entities staged for CREATE
        self._pending: list[Any] = []
        # Entities staged for DETACH DELETE
        self._deleted: list[Any] = []

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, entity: Any) -> None:
        """Register a transient/detached entity as pending (staged for CREATE)."""
        if entity not in self._pending:
            self._pending.append(entity)
            log.debug("Staged for create: %r", entity)

    def add_all(self, entities: list[Any]) -> None:
        """Batch ``add``."""
        for e in entities:
            self.add(e)

    def delete(self, entity: Any) -> None:
        """Mark a persistent entity for DETACH DELETE on next flush.

        Raises ``DetachedEntityError`` if the entity is not known to this session.
        """
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        in_identity_map = (cls, pk) in self._identity_map
        in_pending = entity in self._pending

        if not in_identity_map and not in_pending:
            raise DetachedEntityError(
                f"Entity {entity!r} is not tracked by this session; "
                "call session.add() first or load it via session.get()."
            )

        if entity not in self._deleted:
            self._deleted.append(entity)
        # If it was in pending (never flushed), also remove from pending
        if entity in self._pending:
            self._pending.remove(entity)
        log.debug("Staged for delete: %r", entity)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, cls: type, pk: Any, fetch: list[str] | None = None) -> Any | None:  # noqa: ARG002
        """Return entity from identity map or query graph; ``None`` if not found.

        ``fetch`` is accepted for API compatibility but relationship eager-loading
        is implemented in Phase 3.
        """
        key = (cls, pk)
        if key in self._identity_map:
            entity = self._identity_map[key]
            if entity.__dict__.get("_expired"):
                self._reload(entity, cls, pk)
            return entity

        cypher, params = self._mapper.build_get_query(cls, pk)
        result = self._graph.query(cypher, params)

        if not result.result_set:
            return None

        falkor_node = result.result_set[0][0]
        entity = self._mapper.decode_node(falkor_node, cls)
        actual_pk = self._mapper.get_pk_value(entity)
        self._identity_map[(cls, actual_pk)] = entity
        log.debug("Loaded %s pk=%r from graph", cls.__name__, actual_pk)
        return entity

    # ------------------------------------------------------------------
    # Flush / Commit / Rollback
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Execute all pending/dirty/deleted entities against the graph.

        Does **not** clear the identity map.  Each entity write is a separate
        ``graph.query()`` call.  Entities with ``generated=True`` IDs are
        handled individually so the returned ID can be assigned before continuing.
        """
        self._flush_pending()
        self._flush_dirty()
        self._flush_deleted()

    def commit(self) -> None:
        """``flush()`` then clear the pending/deleted tracking sets."""
        self.flush()
        self._pending.clear()
        self._deleted.clear()
        log.debug("Session committed")

    def rollback(self) -> None:
        """Discard un-flushed pending/deleted sets; expire all persistent entities.

        Cannot undo writes already sent to the graph.
        """
        self._pending.clear()
        self._deleted.clear()
        for entity in self._identity_map.values():
            entity.__dict__["_expired"] = True
            entity.__dict__["_dirty"] = False
        log.debug(
            "Session rolled back (pending/deleted cleared; persistent entities expired)"
        )

    # ------------------------------------------------------------------
    # Expire / Refresh
    # ------------------------------------------------------------------

    def expire(self, entity: Any) -> None:
        """Invalidate cached attributes; they will be reloaded on next ``refresh``."""
        entity.__dict__["_expired"] = True

    def refresh(self, entity: Any) -> None:
        """Immediately re-query the entity from the graph and update in-place."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        self._reload(entity, cls, pk)

    # ------------------------------------------------------------------
    # Expunge
    # ------------------------------------------------------------------

    def expunge(self, entity: Any) -> None:
        """Remove entity from session (→ detached); no graph action."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        self._identity_map.pop((cls, pk), None)
        if entity in self._pending:
            self._pending.remove(entity)
        if entity in self._deleted:
            self._deleted.remove(entity)
        log.debug("Expunged %r from session", entity)

    def expunge_all(self) -> None:
        """Expunge all tracked entities."""
        self._identity_map.clear()
        self._pending.clear()
        self._deleted.clear()

    # ------------------------------------------------------------------
    # Raw Cypher
    # ------------------------------------------------------------------

    def execute(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        write: bool = False,  # noqa: ARG002  (reserved for future routing)
    ) -> Any:
        """Execute raw Cypher; returns ``QueryResult``; no entity mapping."""
        return self._graph.query(cypher, params or {})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """``expunge_all()`` and release the graph connection."""
        self.expunge_all()

    def __enter__(self) -> Session:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()

    # ------------------------------------------------------------------
    # Private flush helpers
    # ------------------------------------------------------------------

    def _flush_pending(self) -> None:
        """CREATE all entities in the pending list."""
        for entity in list(self._pending):
            cypher, params = self._mapper.build_create_query(entity)
            result = self._graph.query(cypher, params)

            falkor_node = result.result_set[0][0] if result.result_set else None
            if falkor_node is not None:
                self._mapper.update_entity_from_node(entity, falkor_node)

            entity.__dict__["_new"] = False
            entity.__dict__["_dirty"] = False

            pk = self._mapper.get_pk_value(entity)
            self._identity_map[(type(entity), pk)] = entity
            log.debug("Created %r pk=%r", entity, pk)

        self._pending.clear()

    def _flush_dirty(self) -> None:
        """MERGE/SET all dirty persistent entities."""
        for (_cls, _pk), entity in list(self._identity_map.items()):
            if not entity.__dict__.get("_dirty", False):
                continue
            if entity.__dict__.get("_new", False):
                continue

            cypher, params = self._mapper.build_update_query(entity)
            if not cypher:
                entity.__dict__["_dirty"] = False
                continue

            result = self._graph.query(cypher, params)
            if result.result_set:
                self._mapper.update_entity_from_node(entity, result.result_set[0][0])
            else:
                entity.__dict__["_dirty"] = False

            log.debug("Updated %s", type(entity).__name__)

    def _flush_deleted(self) -> None:
        """DETACH DELETE all entities in the deleted list."""
        for entity in list(self._deleted):
            cypher, params = self._mapper.build_delete_query(entity)
            self._graph.query(cypher, params)

            cls = type(entity)
            pk = self._mapper.get_pk_value(entity)
            self._identity_map.pop((cls, pk), None)
            log.debug("Deleted %s pk=%r", cls.__name__, pk)

        self._deleted.clear()

    def _reload(self, entity: Any, cls: type, pk: Any) -> None:
        """Re-query a single entity from the graph and update it in-place."""
        cypher, params = self._mapper.build_get_query(cls, pk)
        result = self._graph.query(cypher, params)

        if not result.result_set:
            raise EntityNotFoundError(
                f"{cls.__name__} pk={pk!r} no longer exists in the graph"
            )

        falkor_node = result.result_set[0][0]
        self._mapper.update_entity_from_node(entity, falkor_node)
