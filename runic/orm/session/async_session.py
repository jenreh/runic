"""AsyncSession: async unit-of-work manager for graph writes."""

from __future__ import annotations

import logging
import weakref
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar

from runic.orm.core.descriptors import _NOT_LOADED, FieldDescriptor
from runic.orm.exceptions import EntityNotFoundError, LazyLoadError
from runic.orm.mapper.mapper import Mapper
from runic.orm.session._base import _SessionBase

if TYPE_CHECKING:
    from runic.orm.driver import AsyncGraphDriver, GraphResult
    from runic.orm.query.builder import QueryBuilder

log = logging.getLogger(__name__)

_T = TypeVar("_T")


class AsyncSession(_SessionBase):
    """Async unit-of-work manager; mirrors :class:`Session` with ``async`` methods.

    Shares the backend-agnostic bookkeeping (identity map, pending/deleted
    tracking, expunge, relation resolution) with the sync session via
    :class:`~runic.orm.session._base._SessionBase`.

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
        self._init_state(driver, mapper, log_cypher=log_cypher)

    # ------------------------------------------------------------------
    # Internal query runner
    # ------------------------------------------------------------------

    async def _run_query(self, cypher: str, params: dict[str, Any]) -> GraphResult:
        if self._log_cypher:
            log.debug("Cypher: %s | params: %s", cypher, params)
        return await self._driver.execute(cypher, params)

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
    # Refresh
    # ------------------------------------------------------------------

    async def refresh(self, entity: Any) -> None:
        """Immediately re-query the entity from the graph."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        await self._reload(entity, cls, pk)

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
    # Statement-based execution (select() pattern)
    # ------------------------------------------------------------------

    async def scalars(self, stmt: QueryBuilder[_T]) -> list[_T]:
        """Execute a :func:`~runic.orm.query.select` statement; return decoded entities.

        Type-safe: ``await session.scalars(select(User).where(...))`` infers ``list[User]``.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder` created
            via :func:`~runic.orm.query.select`.
        """
        self._require_query_builder(stmt, "scalars")
        with stmt._bound_to(self) as bound:  # noqa: SLF001
            cypher, params = bound.build()
            result = await self._run_query(cypher, params)
            return bound._decode_node_result(result)  # type: ignore[return-value]  # noqa: SLF001

    async def scalar(self, stmt: QueryBuilder[_T]) -> _T | None:
        """Execute a :func:`~runic.orm.query.select` statement; return first entity or ``None``.

        Adds ``LIMIT 1`` internally without permanently modifying the statement.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder`.
        """
        self._require_query_builder(stmt, "scalar")
        old_limit = stmt._limit_val  # noqa: SLF001
        stmt._limit_val = 1  # noqa: SLF001
        try:
            with stmt._bound_to(self) as bound:  # noqa: SLF001
                cypher, params = bound.build()
                result = await self._run_query(cypher, params)
                entities = bound._decode_node_result(result)  # noqa: SLF001
                return entities[0] if entities else None  # type: ignore[return-value]
        finally:
            stmt._limit_val = old_limit  # noqa: SLF001

    async def all_rows(self, stmt: QueryBuilder[Any]) -> list[dict[str, Any]]:
        """Execute a :func:`~runic.orm.query.select` statement; return column-keyed dicts.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder`.
        """
        self._require_query_builder(stmt, "all_rows")
        with stmt._bound_to(self) as bound:  # noqa: SLF001
            cypher, params = bound.build()
            result = await self._run_query(cypher, params)
            return bound._decode_rows_as_dicts(result)  # noqa: SLF001

    async def all_with_edges(self, stmt: QueryBuilder[Any]) -> list[tuple[Any, ...]]:
        """Execute a :func:`~runic.orm.query.select` statement; return ``(NodeA, Edge, NodeB)`` tuples.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder` with
            ``return_nodes()`` and ``return_edge()`` configured.
        """
        self._require_query_builder(stmt, "all_with_edges")
        with stmt._bound_to(self) as bound:  # noqa: SLF001
            cypher, params = bound.build()
            result = await self._run_query(cypher, params)
            return bound._decode_edge_result(result)  # noqa: SLF001

    async def count(self, stmt: QueryBuilder[Any]) -> int:
        """Execute a :func:`~runic.orm.query.select` statement; return the row count.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder`.
        """
        from runic.orm.query.expressions import count as _count_fn

        self._require_query_builder(stmt, "count")
        # Can't call sync stmt.count() (uses sync _session.execute); replicate its logic async.
        old_limit = stmt._limit_val  # noqa: SLF001
        old_agg = stmt._agg_exprs  # noqa: SLF001
        old_group = stmt._group_by_alias  # noqa: SLF001
        old_return = stmt._return_aliases  # noqa: SLF001
        old_project = stmt._project_fields  # noqa: SLF001
        stmt._agg_exprs = [_count_fn("*").as_("_count")]  # noqa: SLF001
        stmt._group_by_alias = None  # noqa: SLF001
        stmt._return_aliases = None  # noqa: SLF001
        stmt._project_fields = []  # noqa: SLF001
        try:
            with stmt._bound_to(self) as bound:  # noqa: SLF001
                cypher, params = bound.build()
                result = await self._run_query(cypher, params)
                return int(result.rows[0][0]) if result.rows else 0
        finally:
            stmt._limit_val = old_limit  # noqa: SLF001
            stmt._agg_exprs = old_agg  # noqa: SLF001
            stmt._group_by_alias = old_group  # noqa: SLF001
            stmt._return_aliases = old_return  # noqa: SLF001
            stmt._project_fields = old_project  # noqa: SLF001

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

    async def _reload(self, entity: Any, cls: type, pk: Any) -> None:
        cypher, params = self._mapper.build_get_query(cls, pk)
        result = await self._run_query(cypher, params)

        if not result.rows:
            raise EntityNotFoundError(
                f"{cls.__name__} pk={pk!r} no longer exists in the graph"
            )

        self._mapper.update_entity_from_node(entity, result.rows[0][0])
