"""AsyncSession: async unit-of-work manager for graph writes."""

from __future__ import annotations

import logging
import weakref
from types import TracebackType
from typing import TYPE_CHECKING, Any

from runic.orm.core.descriptors import _NOT_LOADED, FieldDescriptor, FieldInfo
from runic.orm.core.metadata import metadata as _global_metadata
from runic.orm.exceptions import DetachedEntityError, EntityNotFoundError, LazyLoadError
from runic.orm.mapper.mapper import Mapper
from runic.orm.mapper.relationship_loader import RelationshipLoader
from runic.orm.mapper.relationship_writer import RelationshipWriter

if TYPE_CHECKING:
    from runic.orm.driver import AsyncGraphDriver, GraphResult

log = logging.getLogger(__name__)


class AsyncSession:
    """Async unit-of-work manager; mirrors :class:`Session` with ``async`` methods.

    Use as an async context manager::

        async with AsyncSession(graph) as session:
            alice = await session.get(Person, "alice-id")
            alice.email = "new@example.com"
            await session.commit()

    Lazy relationship loading is **not** supported in async context because
    ``Field.__get__`` cannot ``await``.  Use ``fetch=[...]`` on ``get()`` instead.
    """

    def __init__(
        self,
        driver: AsyncGraphDriver,
        mapper: Mapper | None = None,
        *,
        log_cypher: bool = False,
    ) -> None:
        self._driver = driver
        self._log_cypher = log_cypher
        self._mapper: Mapper = (
            mapper
            if mapper is not None
            else Mapper(_global_metadata, dialect=driver.dialect)
        )
        self._rel_loader = RelationshipLoader(self._mapper.meta, self._mapper)
        self._rel_writer = RelationshipWriter(self._mapper.meta, self._mapper)
        self._identity_map: dict[tuple[type, Any], Any] = {}
        self._pending: list[Any] = []
        self._deleted: list[Any] = []

    # ------------------------------------------------------------------
    # Internal query runner
    # ------------------------------------------------------------------

    async def _run_query(self, cypher: str, params: dict[str, Any]) -> GraphResult:
        if self._log_cypher:
            log.debug("Cypher: %s | params: %s", cypher, params)
        return await self._driver.execute(cypher, params)

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
    # Properties (used by AsyncRepository)
    # ------------------------------------------------------------------

    @property
    def mapper(self) -> Mapper:
        """Return the Mapper used by this session."""
        return self._mapper

    @property
    def rel_loader(self) -> RelationshipLoader:
        """Return the RelationshipLoader used by this session."""
        return self._rel_loader

    def register_or_get(self, entity: Any) -> Any:
        """Register *entity* in the identity map; return existing instance if present."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        key = (cls, pk)
        if key in self._identity_map:
            return self._identity_map[key]
        entity.__dict__["_session"] = weakref.ref(self)
        self._identity_map[key] = entity
        return entity

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def get(
        self, cls: type, pk: Any, fetch: list[str] | None = None
    ) -> Any | None:
        """Return entity from identity map or query graph asynchronously.

        Pass ``fetch=["rel_name", ...]`` to eager-load relationships in the
        same Cypher query using ``OPTIONAL MATCH``.
        """
        key = (cls, pk)
        if key in self._identity_map:
            entity = self._identity_map[key]
            if entity.__dict__.get("_expired"):
                await self._reload(entity, cls, pk)
            return entity

        if fetch:
            return await self._get_with_fetch(cls, pk, fetch)

        cypher, params = self._mapper.build_get_query(cls, pk)
        result = await self._run_query(cypher, params)

        if not result.rows:
            return None

        raw_node = result.rows[0][0]
        entity = self._mapper.decode_node(raw_node, cls)
        actual_pk = self._mapper.get_pk_value(entity)
        self._register_entity(entity, cls, actual_pk)
        return entity

    def load_relationship(self, entity: Any, field_name: str) -> Any:  # noqa: ARG002
        """Raise ``LazyLoadError``; lazy loading is not supported in async sessions.

        Access ``entity.rel_field`` from within an async context manager triggers
        this via ``Field._trigger_lazy_load``.  Use ``fetch=[field_name]`` on
        ``get()`` for eager loading instead.
        """
        raise LazyLoadError(
            f"Lazy relationship loading is not supported in AsyncSession. "
            f"Use 'await session.get(..., fetch=[{field_name!r}])' instead."
        )

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
        entity.__dict__.pop("_session", None)
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        self._identity_map.pop((cls, pk), None)
        if entity in self._pending:
            self._pending.remove(entity)
        if entity in self._deleted:
            self._deleted.remove(entity)

    def expunge_all(self) -> None:
        """Expunge all tracked entities."""
        for entity in self._identity_map.values():
            entity.__dict__.pop("_session", None)
        for entity in self._pending:
            entity.__dict__.pop("_session", None)
        self._identity_map.clear()
        self._pending.clear()
        self._deleted.clear()

    # ------------------------------------------------------------------
    # Relationship mutations
    # ------------------------------------------------------------------

    async def relate(
        self,
        source: Any,
        field_name: str | FieldDescriptor,
        target: Any,
        edge: Any | None = None,
    ) -> None:
        """Create or update a relationship between *source* and *target*.

        Uses ``MERGE`` semantics: if the relationship already exists its edge
        properties are updated; if not, it is created.  Pass an ``Edge`` model
        instance as *edge* to write properties on the relationship itself.

        *field_name* may be a plain string **or** the class-level descriptor
        attribute (e.g. ``User.invited_trips``) for type-safe call sites.

        The cached value of the relation field on *source* is invalidated after
        the write so the next access re-fetches fresh data from the graph.
        """
        fi = self._resolve_relation_fi(source, field_name)
        cypher, params = self._rel_writer.build_relate_query(source, fi, target, edge)
        await self._run_query(cypher, params)
        source.__dict__[fi.name] = _NOT_LOADED
        log.debug("Related %r -[%s]-> %r", source, fi.field.relationship, target)

    async def unrelate(
        self,
        source: Any,
        field_name: str | FieldDescriptor,
        target: Any,
    ) -> None:
        """Delete the relationship between *source* and *target*.

        *field_name* may be a plain string **or** the class-level descriptor
        attribute (e.g. ``User.invited_trips``) for type-safe call sites.

        The cached value of the relation field on *source* is invalidated after
        the write so the next access re-fetches fresh data from the graph.
        """
        fi = self._resolve_relation_fi(source, field_name)
        cypher, params = self._rel_writer.build_unrelate_query(source, fi, target)
        await self._run_query(cypher, params)
        source.__dict__[fi.name] = _NOT_LOADED
        log.debug("Unrelated %r -[%s]-x %r", source, fi.field.relationship, target)

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
        return await self._run_query(cypher, params or {})

    # ------------------------------------------------------------------
    # Query builder entry points
    # ------------------------------------------------------------------

    def query(self, cls: type[Any]) -> Any:
        """Return an :class:`~runic.orm.query.builder.AsyncQueryBuilder` for *cls*.

        Async entry point for the fluent query builder.  Use ``await`` on the
        terminal methods (``all()``, ``one()``, ``count()``, etc.)::

            async with AsyncSession(graph) as session:
                users = await (
                    session.query(User).where(User.active == True).limit(20).all()
                )
        """
        from runic.orm.query.specialised import AsyncQueryBuilder

        return AsyncQueryBuilder(self, cls)

    def fulltext_search(
        self,
        cls: type[Any],
        *,
        query: str,
        fields: list[str] | None = None,
    ) -> Any:
        """Async fulltext search; mirrors :meth:`~runic.orm.session.session.Session.fulltext_search`."""
        from runic.orm.query.specialised import FulltextQueryBuilder

        return FulltextQueryBuilder(self, cls, query=query, fields=fields)

    def vector_search(
        self,
        cls: type[Any],
        *,
        field: Any,
        vector: list[float],
        k: int = 10,
    ) -> Any:
        """Async vector KNN search; mirrors :meth:`~runic.orm.session.session.Session.vector_search`."""
        from runic.orm.query.specialised import VectorQueryBuilder

        return VectorQueryBuilder(self, cls, field=field, vector=vector, k=k)

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
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_with_fetch(self, cls: type, pk: Any, fetch: list[str]) -> Any | None:
        """Load entity and eager-fetch named relationship fields in one query."""
        cypher, params, fetch_meta = self._rel_loader.build_get_with_fetch_query(
            cls, pk, fetch
        )
        result = await self._run_query(cypher, params)

        if not result.rows:
            return None

        row = result.rows[0]
        raw_node = row[0]
        entity = self._mapper.decode_node(raw_node, cls)
        related = self._rel_loader.decode_eager_columns(row, entity, fetch_meta)

        actual_pk = self._mapper.get_pk_value(entity)
        self._register_entity(entity, cls, actual_pk)
        self._inject_session_into(related)
        return entity

    def _register_entity(self, entity: Any, query_cls: type, pk: Any) -> None:
        """Add entity to identity map and inject weak session reference."""
        entity.__dict__["_session"] = weakref.ref(self)
        self._identity_map[(query_cls, pk)] = entity

    def _inject_session_into(self, decoded: Any) -> None:
        """Inject ``_session`` into a single entity or list of entities."""
        ref = weakref.ref(self)
        if isinstance(decoded, list):
            for e in decoded:
                if e is not None:
                    e.__dict__["_session"] = ref
        elif decoded is not None:
            decoded.__dict__["_session"] = ref

    async def _flush_pending(self) -> None:
        for entity in list(self._pending):
            cypher, params = self._mapper.build_create_query(entity)
            result = await self._run_query(cypher, params)

            raw_node = result.rows[0][0] if result.rows else None
            if raw_node is not None:
                self._mapper.update_entity_from_node(entity, raw_node)

            entity.__dict__["_new"] = False
            entity.__dict__["_dirty"] = False

            pk = self._mapper.get_pk_value(entity)
            entity.__dict__["_session"] = weakref.ref(self)
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

            result = await self._run_query(cypher, params)
            if result.rows:
                self._mapper.update_entity_from_node(entity, result.rows[0][0])
            else:
                entity.__dict__["_dirty"] = False

    async def _flush_deleted(self) -> None:
        for entity in list(self._deleted):
            cypher, params = self._mapper.build_delete_query(entity)
            await self._run_query(cypher, params)

            cls = type(entity)
            pk = self._mapper.get_pk_value(entity)
            self._identity_map.pop((cls, pk), None)
            entity.__dict__.pop("_session", None)

        self._deleted.clear()

    def _resolve_relation_fi(
        self, source: Any, field_name: str | FieldDescriptor
    ) -> FieldInfo:
        """Return the ``FieldInfo`` for a declared ``Relation`` field on *source*.

        *field_name* may be a plain string or the class-level ``FieldDescriptor``
        (e.g. ``User.invited_trips``).

        Raises ``TypeError`` when *field_name* does not correspond to a Relation.
        """
        name = (
            field_name.name if isinstance(field_name, FieldDescriptor) else field_name
        )
        node_meta = self._mapper.require_node_meta(type(source))
        fi = next((f for f in node_meta.fields if f.name == name), None)
        if fi is None or fi.field.relationship is None:
            raise TypeError(
                f"{type(source).__name__!r} has no Relation field named {name!r}"
            )
        return fi

    async def _reload(self, entity: Any, cls: type, pk: Any) -> None:
        cypher, params = self._mapper.build_get_query(cls, pk)
        result = await self._run_query(cypher, params)

        if not result.rows:
            raise EntityNotFoundError(
                f"{cls.__name__} pk={pk!r} no longer exists in the graph"
            )

        self._mapper.update_entity_from_node(entity, result.rows[0][0])
