"""Session: unit-of-work manager for graph writes."""

from __future__ import annotations

import logging
import weakref
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar

from runic.orm.core.descriptors import _NOT_LOADED, FieldDescriptor, FieldInfo
from runic.orm.core.metadata import metadata as _global_metadata
from runic.orm.exceptions import DetachedEntityError, EntityNotFoundError
from runic.orm.mapper.mapper import Mapper
from runic.orm.mapper.relationship_loader import RelationshipLoader
from runic.orm.mapper.relationship_writer import RelationshipWriter

if TYPE_CHECKING:
    from runic.orm.driver import GraphDriver, GraphResult
    from runic.orm.query.builder import QueryBuilder

log = logging.getLogger(__name__)

_T = TypeVar("_T")


class Session:
    """Sync unit-of-work manager.

    Owns all mutations (``add``, ``delete``), single-entity lookup (``get``),
    identity map, and flush/commit lifecycle.  Repositories hold a session
    reference and delegate writes and PK lookups to it.

    **Transaction model** — determined by the injected driver:

    - **FalkorDB** (no native multi-query transactions): each ``GRAPH.QUERY``
      is individually atomic.  ``commit()`` flushes pending writes;
      ``rollback()`` discards un-flushed state only — it cannot undo writes
      already sent to the graph.
    - **Bolt-based drivers** (Neo4j, Memgraph, ArcadeDB): full ACID
      transactions via the Bolt protocol.  The first query lazily opens a Bolt
      transaction; ``commit()`` / ``rollback()`` commit or discard all changes
      as a single atomic unit.
    - **Apache AGE** (psycopg3): full PostgreSQL ACID transactions.  psycopg3
      starts an implicit ``BEGIN`` on the first SQL statement; ``commit()`` /
      ``rollback()`` map to ``conn.commit()`` / ``conn.rollback()``.

    Drivers that support explicit transactions implement the
    :class:`~runic.orm.driver.TransactionalGraphDriver` protocol.  The Session
    detects this via ``isinstance`` and wires commit/rollback accordingly.
    """

    def __init__(
        self,
        driver: GraphDriver,
        mapper: Mapper | None = None,
        *,
        log_cypher: bool = False,
    ) -> None:
        from runic.orm.driver import TransactionalGraphDriver

        self._driver = driver
        self._log_cypher = log_cypher
        self._mapper: Mapper = (
            mapper
            if mapper is not None
            else Mapper(_global_metadata, dialect=driver.dialect)
        )
        self._rel_loader = RelationshipLoader(self._mapper.meta, self._mapper)
        self._rel_writer = RelationshipWriter(self._mapper.meta, self._mapper)
        # Identity map: (EntityClass, pk) → entity instance
        self._identity_map: dict[tuple[type, Any], Any] = {}
        # Entities staged for CREATE
        self._pending: list[Any] = []
        # Entities staged for DETACH DELETE
        self._deleted: list[Any] = []
        # True when a driver-level transaction is open (lazy-begin on first query)
        self._in_transaction: bool = False
        self._is_transactional: bool = isinstance(driver, TransactionalGraphDriver)

    # ------------------------------------------------------------------
    # Internal query runner
    # ------------------------------------------------------------------

    def _run_query(self, cypher: str, params: dict[str, Any]) -> GraphResult:
        if self._log_cypher:
            log.debug("Cypher: %s | params: %s", cypher, params)
        if self._is_transactional and not self._in_transaction:
            self._driver.begin()  # ty: ignore[unresolved-attribute]
            self._in_transaction = True
        return self._driver.execute(cypher, params)

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
    # Properties (used by Repository)
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
        """Register *entity* in the identity map; return existing instance if present.

        Used by Repository reads to deduplicate against entities already loaded
        in this session (fulfilling the identity-map guarantee).
        """
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

    def get(self, cls: type, pk: Any, fetch: list[str] | None = None) -> Any | None:
        """Return entity from identity map or query graph; ``None`` if not found.

        Pass ``fetch=["rel_name", ...]`` to eager-load relationship fields in
        the same Cypher query using ``OPTIONAL MATCH``.
        """
        key = (cls, pk)
        if key in self._identity_map:
            entity = self._identity_map[key]
            if entity.__dict__.get("_expired"):
                self._reload(entity, cls, pk)
            return entity

        if fetch:
            return self._get_with_fetch(cls, pk, fetch)

        cypher, params = self._mapper.build_get_query(cls, pk)
        result = self._run_query(cypher, params)

        if not result.rows:
            return None

        raw_node = result.rows[0][0]
        entity = self._mapper.decode_node(raw_node, cls)
        actual_pk = self._mapper.get_pk_value(entity)
        self._register_entity(entity, cls, actual_pk)
        log.debug("Loaded %s pk=%r from graph", cls.__name__, actual_pk)
        return entity

    def load_relationship(self, entity: Any, field_name: str) -> Any:
        """Load a lazy relationship field and cache the result on the entity.

        Called by ``Field._trigger_lazy_load`` when a ``_NOT_LOADED`` sentinel
        is accessed on an entity that is attached to this session.
        Writes directly to ``entity.__dict__`` to bypass the dirty-tracking
        descriptor.
        """
        cls = type(entity)
        node_meta = self._mapper.require_node_meta(cls)
        fi = next((f for f in node_meta.fields if f.name == field_name), None)
        if fi is None or fi.field.relationship is None:
            return None

        cypher, params = self._rel_loader.build_lazy_load_query(entity, fi)
        result = self._run_query(cypher, params)
        decoded = self._rel_loader.decode_lazy_result(result, fi)

        entity.__dict__[field_name] = decoded
        self._inject_session_into(decoded)
        log.debug("Lazy-loaded %r.%s", entity, field_name)
        return decoded

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
        """``flush()`` then clear the pending/deleted tracking sets.

        For transactional drivers (Bolt, AGE), also commits the active
        database transaction so all flushed writes become durable and visible.
        """
        self.flush()
        self._pending.clear()
        self._deleted.clear()
        if self._in_transaction:
            self._driver.commit()  # ty: ignore[unresolved-attribute]
            self._in_transaction = False
        log.debug("Session committed")

    def rollback(self) -> None:
        """Discard un-flushed pending/deleted sets; expire all persistent entities.

        For transactional drivers (Bolt, AGE), also rolls back the active
        database transaction — writes already flushed but not yet committed
        are discarded atomically.  For FalkorDB (no native transactions),
        only un-flushed in-memory state is cleared; writes already sent to
        the graph cannot be undone.
        """
        self._pending.clear()
        self._deleted.clear()
        for entity in self._identity_map.values():
            entity.__dict__["_expired"] = True
            entity.__dict__["_dirty"] = False
        if self._in_transaction:
            self._driver.rollback()  # ty: ignore[unresolved-attribute]
            self._in_transaction = False
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
        entity.__dict__.pop("_session", None)
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

    def relate(
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
        self._run_query(cypher, params)
        source.__dict__[fi.name] = _NOT_LOADED
        log.debug("Related %r -[%s]-> %r", source, fi.field.relationship, target)

    def unrelate(
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
        self._run_query(cypher, params)
        source.__dict__[fi.name] = _NOT_LOADED
        log.debug("Unrelated %r -[%s]-x %r", source, fi.field.relationship, target)

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
        return self._run_query(cypher, params or {})

    # ------------------------------------------------------------------
    # Statement-based execution (select() pattern)
    # ------------------------------------------------------------------

    def scalars(self, stmt: QueryBuilder[_T]) -> list[_T]:
        """Execute a :func:`~runic.orm.query.select` statement; return decoded entities.

        Type-safe: ``session.scalars(select(User).where(...))`` infers ``list[User]``.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder` created
            via :func:`~runic.orm.query.select`.
        """
        self._require_query_builder(stmt, "scalars")
        with stmt._bound_to(self) as bound:  # noqa: SLF001
            cypher, params = bound.build()
            result = self._run_query(cypher, params)
            return bound._decode_node_result(result)  # type: ignore[return-value]  # noqa: SLF001

    def scalar(self, stmt: QueryBuilder[_T]) -> _T | None:
        """Execute a :func:`~runic.orm.query.select` statement; return first entity or ``None``.

        Adds ``LIMIT 1`` internally without permanently modifying the statement.
        Type-safe: ``session.scalar(select(User).where(...))`` infers ``User | None``.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder` created
            via :func:`~runic.orm.query.select`.
        """
        self._require_query_builder(stmt, "scalar")
        old_limit = stmt._limit_val  # noqa: SLF001
        stmt._limit_val = 1  # noqa: SLF001
        try:
            with stmt._bound_to(self) as bound:  # noqa: SLF001
                cypher, params = bound.build()
                result = self._run_query(cypher, params)
                entities = bound._decode_node_result(result)  # noqa: SLF001
                return entities[0] if entities else None  # type: ignore[return-value]
        finally:
            stmt._limit_val = old_limit  # noqa: SLF001

    def all_rows(self, stmt: QueryBuilder[Any]) -> list[dict[str, Any]]:
        """Execute a :func:`~runic.orm.query.select` statement; return column-keyed dicts.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder`.
        """
        self._require_query_builder(stmt, "all_rows")
        with stmt._bound_to(self) as bound:  # noqa: SLF001
            cypher, params = bound.build()
            result = self._run_query(cypher, params)
            return bound._decode_rows_as_dicts(result)  # noqa: SLF001

    def all_with_edges(self, stmt: QueryBuilder[Any]) -> list[tuple[Any, ...]]:
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
            result = self._run_query(cypher, params)
            return bound._decode_edge_result(result)  # noqa: SLF001

    def count(self, stmt: QueryBuilder[Any]) -> int:
        """Execute a :func:`~runic.orm.query.select` statement; return the row count.

        Parameters
        ----------
        stmt:
            An unbound :class:`~runic.orm.query.builder.QueryBuilder`.
        """
        self._require_query_builder(stmt, "count")
        with stmt._bound_to(self) as bound:  # noqa: SLF001
            return bound.count()

    # ------------------------------------------------------------------
    # Query builder entry points
    # ------------------------------------------------------------------

    def query(self, cls: type[Any]) -> Any:
        """Return a :class:`~runic.orm.query.builder.QueryBuilder` for *cls*.

        This is the primary entry point for the fluent query builder API::

            users = (
                session.query(User)
                .where(User.active == True)
                .order_by(User.name)
                .limit(20)
                .all()
            )

        Parameters
        ----------
        cls:
            A registered :class:`~runic.orm.core.models.Node` subclass.

        Returns
        -------
        QueryBuilder[cls]
        """
        from runic.orm.query.builder import QueryBuilder

        return QueryBuilder(self, cls)

    def fulltext_search(
        self,
        cls: type[Any],
        *,
        query: str,
        fields: list[str] | None = None,
    ) -> Any:
        """Return a :class:`~runic.orm.query.builder.FulltextQueryBuilder` for *cls*.

        Uses FalkorDB's ``CALL db.idx.fulltext.queryNodes()`` procedure.  The
        node label must have a fulltext index created.

        Parameters
        ----------
        cls:
            A registered :class:`~runic.orm.core.models.Node` subclass with
            at least one field with ``index_type="FULLTEXT"``.
        query:
            The fulltext search string.
        fields:
            Optional list of field names to search (informational; the
            procedure uses the index it finds for the label).

        Example
        -------
        .. code-block:: python

            posts = (
                session.fulltext_search(Post, query="graph databases")
                .where(Post.published == True)
                .limit(10)
                .all()
            )
        """
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
        """Return a :class:`~runic.orm.query.builder.VectorQueryBuilder` for *cls*.

        Performs a K-Nearest-Neighbour search using FalkorDB's HNSW index.

        Parameters
        ----------
        cls:
            A registered :class:`~runic.orm.core.models.Node` subclass.
        field:
            The :class:`~runic.orm.core.descriptors.FieldDescriptor` of the
            ``Vector`` field to search (e.g. ``Document.embedding``).
        vector:
            The query embedding as a list of floats.
        k:
            Number of nearest neighbours to return (default ``10``).

        Example
        -------
        .. code-block:: python

            similar = (
                session.vector_search(
                    Document, field=Document.embedding, vector=my_vec, k=5
                )
                .where(Document.active == True)
                .all()
            )
        """
        from runic.orm.query.specialised import VectorQueryBuilder

        return VectorQueryBuilder(self, cls, field=field, vector=vector, k=k)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Expunge all tracked entities; roll back any orphaned transaction.

        If ``close()`` is called without a prior ``commit()`` or
        ``rollback()`` (e.g. the session was not used as a context manager),
        any active driver-level transaction is rolled back to release the
        connection cleanly.
        """
        if self._in_transaction:
            try:
                self._driver.rollback()  # ty: ignore[unresolved-attribute]
            except Exception:
                log.warning(
                    "Session.close(): driver rollback failed; connection may leak"
                )
            self._in_transaction = False
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
    # Private helpers
    # ------------------------------------------------------------------

    def _get_with_fetch(self, cls: type, pk: Any, fetch: list[str]) -> Any | None:
        """Load entity and eager-fetch named relationship fields in one Cypher query."""
        cypher, params, fetch_meta = self._rel_loader.build_get_with_fetch_query(
            cls, pk, fetch
        )
        result = self._run_query(cypher, params)

        if not result.rows:
            return None

        row = result.rows[0]
        raw_node = row[0]
        entity = self._mapper.decode_node(raw_node, cls)
        related = self._rel_loader.decode_eager_columns(row, entity, fetch_meta)

        actual_pk = self._mapper.get_pk_value(entity)
        self._register_entity(entity, cls, actual_pk)
        self._inject_session_into(related)
        log.debug("Loaded %s pk=%r with fetch=%r", cls.__name__, actual_pk, fetch)
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

    def _flush_pending(self) -> None:
        """CREATE all entities in the pending list."""
        for entity in list(self._pending):
            cypher, params = self._mapper.build_create_query(entity)
            result = self._run_query(cypher, params)

            raw_node = result.rows[0][0] if result.rows else None
            if raw_node is not None:
                self._mapper.update_entity_from_node(entity, raw_node)

            entity.__dict__["_new"] = False
            entity.__dict__["_dirty"] = False

            pk = self._mapper.get_pk_value(entity)
            entity.__dict__["_session"] = weakref.ref(self)
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

            result = self._run_query(cypher, params)
            if result.rows:
                self._mapper.update_entity_from_node(entity, result.rows[0][0])
            else:
                entity.__dict__["_dirty"] = False

            log.debug("Updated %s", type(entity).__name__)

    def _flush_deleted(self) -> None:
        """DETACH DELETE all entities in the deleted list."""
        for entity in list(self._deleted):
            cypher, params = self._mapper.build_delete_query(entity)
            self._run_query(cypher, params)

            cls = type(entity)
            pk = self._mapper.get_pk_value(entity)
            self._identity_map.pop((cls, pk), None)
            entity.__dict__.pop("_session", None)
            log.debug("Deleted %s pk=%r", cls.__name__, pk)

        self._deleted.clear()

    def _require_query_builder(self, stmt: Any, method: str) -> None:
        """Raise TypeError if *stmt* is not a QueryBuilder."""
        from runic.orm.query.builder import QueryBuilder

        if not isinstance(stmt, QueryBuilder):
            raise TypeError(f"{method}() expects a QueryBuilder created by select()")

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

    def _reload(self, entity: Any, cls: type, pk: Any) -> None:
        """Re-query a single entity from the graph and update it in-place."""
        cypher, params = self._mapper.build_get_query(cls, pk)
        result = self._run_query(cypher, params)

        if not result.rows:
            raise EntityNotFoundError(
                f"{cls.__name__} pk={pk!r} no longer exists in the graph"
            )

        self._mapper.update_entity_from_node(entity, result.rows[0][0])
