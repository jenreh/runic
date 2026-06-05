"""AsyncSession: async parity of Session for FalkorDB async graph clients."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any

from runic.orm.core.metadata import metadata as _global_metadata
from runic.orm.exceptions import DetachedEntityError, EntityNotFoundError
from runic.orm.mapper.mapper import Mapper

log = logging.getLogger(__name__)


class AsyncSession:
    """Async unit-of-work manager; mirrors :class:`Session` with ``async`` methods.

    Use as an async context manager::

        async with AsyncSession(graph) as session:
            alice = await session.get(Person, "alice-id")
            alice.email = "new@example.com"
            await session.commit()
    """

    def __init__(self, graph: Any, mapper: Mapper | None = None) -> None:
        self._graph = graph
        self._mapper: Mapper = (
            mapper if mapper is not None else Mapper(_global_metadata)
        )
        self._identity_map: dict[tuple[type, Any], Any] = {}
        self._pending: list[Any] = []
        self._deleted: list[Any] = []

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, entity: Any) -> None:
        """Register a transient/detached entity as pending."""
        if entity not in self._pending:
            self._pending.append(entity)

    def add_all(self, entities: list[Any]) -> None:
        """Batch ``add``."""
        for e in entities:
            self.add(e)

    def delete(self, entity: Any) -> None:
        """Mark a persistent entity for DETACH DELETE on next flush."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        in_identity_map = (cls, pk) in self._identity_map
        in_pending = entity in self._pending

        if not in_identity_map and not in_pending:
            raise DetachedEntityError(
                f"Entity {entity!r} is not tracked by this session."
            )

        if entity not in self._deleted:
            self._deleted.append(entity)
        if entity in self._pending:
            self._pending.remove(entity)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def get(
        self, cls: type, pk: Any, fetch: list[str] | None = None  # noqa: ARG002
    ) -> Any | None:
        """Return entity from identity map or query graph asynchronously."""
        key = (cls, pk)
        if key in self._identity_map:
            entity = self._identity_map[key]
            if entity.__dict__.get("_expired"):
                await self._reload(entity, cls, pk)
            return entity

        cypher, params = self._mapper.build_get_query(cls, pk)
        result = await self._graph.query(cypher, params)

        if not result.result_set:
            return None

        falkor_node = result.result_set[0][0]
        entity = self._mapper.decode_node(falkor_node, cls)
        actual_pk = self._mapper.get_pk_value(entity)
        self._identity_map[(cls, actual_pk)] = entity
        return entity

    # ------------------------------------------------------------------
    # Flush / Commit / Rollback
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        """Execute all pending/dirty/deleted entities against the graph."""
        await self._flush_pending()
        await self._flush_dirty()
        await self._flush_deleted()

    async def commit(self) -> None:
        """``flush()`` then clear the pending/deleted tracking sets."""
        await self.flush()
        self._pending.clear()
        self._deleted.clear()

    async def rollback(self) -> None:
        """Discard un-flushed pending/deleted sets; expire all persistent entities."""
        self._pending.clear()
        self._deleted.clear()
        for entity in self._identity_map.values():
            entity.__dict__["_expired"] = True
            entity.__dict__["_dirty"] = False

    # ------------------------------------------------------------------
    # Expire / Refresh
    # ------------------------------------------------------------------

    def expire(self, entity: Any) -> None:
        """Invalidate cached attributes."""
        entity.__dict__["_expired"] = True

    async def refresh(self, entity: Any) -> None:
        """Immediately re-query the entity from the graph."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        await self._reload(entity, cls, pk)

    # ------------------------------------------------------------------
    # Expunge
    # ------------------------------------------------------------------

    def expunge(self, entity: Any) -> None:
        """Remove entity from session; no graph action."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        self._identity_map.pop((cls, pk), None)
        if entity in self._pending:
            self._pending.remove(entity)
        if entity in self._deleted:
            self._deleted.remove(entity)

    def expunge_all(self) -> None:
        """Expunge all tracked entities."""
        self._identity_map.clear()
        self._pending.clear()
        self._deleted.clear()

    # ------------------------------------------------------------------
    # Raw Cypher
    # ------------------------------------------------------------------

    async def execute(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        write: bool = False,  # noqa: ARG002
    ) -> Any:
        """Execute raw Cypher; returns ``QueryResult``; no entity mapping."""
        return await self._graph.query(cypher, params or {})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """``expunge_all()`` and release the graph connection."""
        self.expunge_all()

    async def __aenter__(self) -> AsyncSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()
        await self.close()

    # ------------------------------------------------------------------
    # Private flush helpers
    # ------------------------------------------------------------------

    async def _flush_pending(self) -> None:
        for entity in list(self._pending):
            cypher, params = self._mapper.build_create_query(entity)
            result = await self._graph.query(cypher, params)

            falkor_node = result.result_set[0][0] if result.result_set else None
            if falkor_node is not None:
                self._mapper.update_entity_from_node(entity, falkor_node)

            entity.__dict__["_new"] = False
            entity.__dict__["_dirty"] = False

            pk = self._mapper.get_pk_value(entity)
            self._identity_map[(type(entity), pk)] = entity

        self._pending.clear()

    async def _flush_dirty(self) -> None:
        for (_cls, _pk), entity in list(self._identity_map.items()):
            if not entity.__dict__.get("_dirty", False):
                continue
            if entity.__dict__.get("_new", False):
                continue

            cypher, params = self._mapper.build_update_query(entity)
            if not cypher:
                entity.__dict__["_dirty"] = False
                continue

            result = await self._graph.query(cypher, params)
            if result.result_set:
                self._mapper.update_entity_from_node(entity, result.result_set[0][0])
            else:
                entity.__dict__["_dirty"] = False

    async def _flush_deleted(self) -> None:
        for entity in list(self._deleted):
            cypher, params = self._mapper.build_delete_query(entity)
            await self._graph.query(cypher, params)

            cls = type(entity)
            pk = self._mapper.get_pk_value(entity)
            self._identity_map.pop((cls, pk), None)

        self._deleted.clear()

    async def _reload(self, entity: Any, cls: type, pk: Any) -> None:
        cypher, params = self._mapper.build_get_query(cls, pk)
        result = await self._graph.query(cypher, params)

        if not result.result_set:
            raise EntityNotFoundError(
                f"{cls.__name__} pk={pk!r} no longer exists in the graph"
            )

        falkor_node = result.result_set[0][0]
        self._mapper.update_entity_from_node(entity, falkor_node)
