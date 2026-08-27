"""Shared state and backend-agnostic behaviour for Session / AsyncSession.

:class:`_SessionBase` holds the unit-of-work bookkeeping that is identical
across the sync and async sessions — identity map, pending/deleted tracking,
entity registration, expunge, and relation-field resolution.

It also holds the *I/O-free halves* of the mirrored execution methods: the
query preparation that runs before a statement is sent (``_prepare_relate``,
``_build_and_bind``, ``_prepare_update``) and the result handling that runs
after it comes back (``_decode_get_result``, ``_finish_create``,
``_finish_delete``, ``_apply_reload_result``, …).  Only the ``await``-aware
middle is left to the two concrete sessions, so a change to *what* a write
does lands here once instead of twice.  The methods deliberately take an
already-executed ``GraphResult`` rather than running the query themselves —
that is what keeps them shareable between a sync and an async caller.

One thing stays duplicated on purpose: the ``log_cypher`` statement log.  It
is emitted from each concrete session so it keeps arriving on the logger
callers actually enable — ``runic.ogm.session.session`` — rather than on this
private module's.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from runic.ogm.core.descriptors import _NOT_LOADED, FieldDescriptor, FieldInfo
from runic.ogm.core.metadata import metadata as _global_metadata
from runic.ogm.exceptions import DetachedEntityError, EntityNotFoundError
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.mapper.relationship_loader import RelationshipLoader
from runic.ogm.mapper.relationship_writer import RelationshipWriter

if TYPE_CHECKING:
    from runic.ogm.driver import GraphResult
    from runic.ogm.query.builder import QueryBuilder

log = logging.getLogger(__name__)


class _SessionBase:
    """Backend-agnostic unit-of-work state shared by the sync and async sessions."""

    _driver: Any
    _log_cypher: bool
    _mapper: Mapper
    _rel_loader: RelationshipLoader
    _rel_writer: RelationshipWriter
    _identity_map: dict[tuple[type, Any], Any]
    _pending: list[Any]
    _deleted: list[Any]

    def _init_state(
        self, driver: Any, mapper: Mapper | None, *, log_cypher: bool
    ) -> None:
        """Initialise the shared session state.  Called from each ``__init__``."""
        self._driver = driver
        self._log_cypher = log_cypher
        self._mapper = (
            mapper
            if mapper is not None
            else Mapper(_global_metadata, dialect=driver.dialect)
        )
        self._rel_loader = RelationshipLoader(self._mapper.meta, self._mapper)
        self._rel_writer = RelationshipWriter(self._mapper.meta, self._mapper)
        # Identity map: (EntityClass, pk) → entity instance
        self._identity_map = {}
        # Entities staged for CREATE
        self._pending = []
        # Entities staged for DETACH DELETE
        self._deleted = []

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
    # Properties (used by repositories)
    # ------------------------------------------------------------------

    @property
    def mapper(self) -> Mapper:
        """Return the Mapper used by this session."""
        return self._mapper

    @property
    def rel_loader(self) -> RelationshipLoader:
        """Return the RelationshipLoader used by this session."""
        return self._rel_loader

    # ------------------------------------------------------------------
    # Identity map
    # ------------------------------------------------------------------

    def register_or_get(self, entity: Any) -> Any:
        """Register *entity* in the identity map; return existing instance if present.

        Used by repository reads to deduplicate against entities already loaded
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

    def decode_and_register_node(self, raw_node: Any, cls: type) -> Any:
        """Decode a raw node into *cls* and register it in the identity map.

        Centralises the decode-then-``register_or_get`` pattern shared by the
        query builder's result decoder and the repositories.
        """
        return self.register_or_get(self._mapper.decode_node(raw_node, cls))

    # ------------------------------------------------------------------
    # Expire / Expunge
    # ------------------------------------------------------------------

    def expire(self, entity: Any) -> None:
        """Invalidate cached attributes; they will be reloaded on next ``refresh``."""
        entity.__dict__["_expired"] = True

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
    # Query builder entry points
    # ------------------------------------------------------------------

    def fulltext_search(
        self,
        cls: type[Any],
        *,
        query: str,
        fields: list[str] | None = None,
    ) -> Any:
        """Return a :class:`~runic.ogm.query.specialised.FulltextQueryBuilder`.

        Uses the backend's fulltext procedure (FalkorDB's
        ``CALL db.idx.fulltext.queryNodes()`` and its equivalents).  The node
        label must have a fulltext index created.

        Parameters
        ----------
        cls:
            A registered :class:`~runic.ogm.core.models.Node` subclass with
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

        On an :class:`~runic.ogm.session.async_session.AsyncSession` the
        builder is the same; ``await`` its terminal instead.
        """
        from runic.ogm.query.specialised import FulltextQueryBuilder

        return FulltextQueryBuilder(self, cls, query=query, fields=fields)

    def vector_search(
        self,
        cls: type[Any],
        *,
        field: Any,
        vector: list[float],
        k: int = 10,
    ) -> Any:
        """Return a :class:`~runic.ogm.query.specialised.VectorQueryBuilder`.

        Performs a K-Nearest-Neighbour search using the backend's vector index.

        Parameters
        ----------
        cls:
            A registered :class:`~runic.ogm.core.models.Node` subclass.
        field:
            The :class:`~runic.ogm.core.descriptors.FieldDescriptor` of the
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

        On an :class:`~runic.ogm.session.async_session.AsyncSession` the
        builder is the same; ``await`` its terminal instead.
        """
        from runic.ogm.query.specialised import VectorQueryBuilder

        return VectorQueryBuilder(self, cls, field=field, vector=vector, k=k)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

    def _require_query_builder(self, stmt: Any, method: str) -> None:
        """Raise TypeError if *stmt* is not a QueryBuilder."""
        from runic.ogm.query.builder import QueryBuilder

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

    # ------------------------------------------------------------------
    # Query preparation — runs before the query is sent
    # ------------------------------------------------------------------

    def _build_and_bind(
        self, bound: QueryBuilder[Any], params: Mapping[str, Any] | None
    ) -> tuple[str, dict[str, Any]]:
        """Compile a session-bound statement and merge the caller's parameters."""
        cypher, _ = bound.build()
        return cypher, bound.bind(params)

    def _prepare_relate(
        self,
        source: Any,
        field_name: str | FieldDescriptor,
        target: Any,
        edge: Any | None,
    ) -> tuple[FieldInfo, str, dict[str, Any]]:
        """Resolve the relation field and build the MERGE query for a ``relate``."""
        fi = self._resolve_relation_fi(source, field_name)
        cypher, params = self._rel_writer.build_relate_query(source, fi, target, edge)
        return fi, cypher, params

    def _prepare_unrelate(
        self, source: Any, field_name: str | FieldDescriptor, target: Any
    ) -> tuple[FieldInfo, str, dict[str, Any]]:
        """Resolve the relation field and build the DELETE query for an ``unrelate``."""
        fi = self._resolve_relation_fi(source, field_name)
        cypher, params = self._rel_writer.build_unrelate_query(source, fi, target)
        return fi, cypher, params

    def _prepare_update(self, entity: Any) -> tuple[str, dict[str, Any]] | None:
        """Build the SET query for a dirty entity, or ``None`` when nothing changed.

        Clears the dirty flag when the mapper reports no writable diff, so the
        caller can simply skip the entity.
        """
        cypher, params = self._mapper.build_update_query(entity)
        if not cypher:
            entity.__dict__["_dirty"] = False
            return None
        return cypher, params

    def _needs_update(self, entity: Any) -> bool:
        """True when a *persistent* entity carries unflushed changes.

        Evaluated per entity as the flush loop reaches it, not up front, so a
        write earlier in the loop can still influence what follows.
        """
        if not entity.__dict__.get("_dirty", False):
            return False
        return not entity.__dict__.get("_new", False)

    # ------------------------------------------------------------------
    # Result handling — runs after the query comes back
    # ------------------------------------------------------------------

    def _decode_get_result(self, result: GraphResult, cls: type) -> Any | None:
        """Register the node a ``get()`` returned; ``None`` when the result is empty."""
        if not result.rows:
            return None

        entity = self._mapper.decode_node(result.rows[0][0], cls)
        actual_pk = self._mapper.get_pk_value(entity)
        self._register_entity(entity, cls, actual_pk)
        log.debug("Loaded %s pk=%r from graph", cls.__name__, actual_pk)
        return entity

    def _decode_fetch_result(
        self,
        result: GraphResult,
        cls: type,
        fetch: list[str],
        fetch_meta: list[tuple[str, FieldInfo]],
    ) -> Any | None:
        """Register the node and its eager-fetched relations from a ``fetch=`` query."""
        if not result.rows:
            return None

        row = result.rows[0]
        entity = self._mapper.decode_node(row[0], cls)
        related = self._rel_loader.decode_eager_columns(row, entity, fetch_meta)

        actual_pk = self._mapper.get_pk_value(entity)
        self._register_entity(entity, cls, actual_pk)
        self._inject_session_into(related)
        log.debug("Loaded %s pk=%r with fetch=%r", cls.__name__, actual_pk, fetch)
        return entity

    def _finish_create(self, entity: Any, result: GraphResult) -> None:
        """Apply a CREATE result to *entity* and promote it from pending to persistent."""
        raw_node = result.rows[0][0] if result.rows else None
        if raw_node is not None:
            self._mapper.update_entity_from_node(entity, raw_node)

        entity.__dict__["_new"] = False
        entity.__dict__["_dirty"] = False

        pk = self._mapper.get_pk_value(entity)
        self._register_entity(entity, type(entity), pk)
        # Drop the entity as soon as its CREATE succeeds so a failure later
        # in the loop cannot re-create it (a durable duplicate on FalkorDB)
        # when the caller retries flush().
        self._pending.remove(entity)
        log.debug("Created %r pk=%r", entity, pk)

    def _finish_update(self, entity: Any, result: GraphResult) -> None:
        """Apply an UPDATE result to *entity*, clearing the dirty flag if it vanished."""
        if result.rows:
            self._mapper.update_entity_from_node(entity, result.rows[0][0])
        else:
            entity.__dict__["_dirty"] = False

        log.debug("Updated %s", type(entity).__name__)

    def _finish_delete(self, entity: Any) -> None:
        """Detach a deleted entity from the session once its DELETE succeeded."""
        cls = type(entity)
        pk = self._mapper.get_pk_value(entity)
        self._identity_map.pop((cls, pk), None)
        entity.__dict__.pop("_session", None)
        # Drop per-entity so a failure later in the loop does not re-issue a
        # DELETE for an already-deleted entity when the caller retries.
        self._deleted.remove(entity)
        log.debug("Deleted %s pk=%r", cls.__name__, pk)

    def _finish_relate(self, source: Any, fi: FieldInfo, target: Any) -> None:
        """Invalidate the cached relation value after a successful ``relate``."""
        source.__dict__[fi.name] = _NOT_LOADED
        log.debug("Related %r -[%s]-> %r", source, fi.field.relationship, target)

    def _finish_unrelate(self, source: Any, fi: FieldInfo, target: Any) -> None:
        """Invalidate the cached relation value after a successful ``unrelate``."""
        source.__dict__[fi.name] = _NOT_LOADED
        log.debug("Unrelated %r -[%s]-x %r", source, fi.field.relationship, target)

    def _apply_reload_result(
        self, entity: Any, cls: type, pk: Any, result: GraphResult
    ) -> None:
        """Update *entity* in place from a re-query; raise if the node is gone."""
        if not result.rows:
            raise EntityNotFoundError(
                f"{cls.__name__} pk={pk!r} no longer exists in the graph"
            )

        self._mapper.update_entity_from_node(entity, result.rows[0][0])

    # ------------------------------------------------------------------
    # Transaction bookkeeping (in-memory only; no driver interaction)
    # ------------------------------------------------------------------

    def _clear_staged(self) -> None:
        """Drop the pending and deleted staging lists."""
        self._pending.clear()
        self._deleted.clear()

    def _discard_uncommitted_state(self) -> None:
        """Rollback bookkeeping: drop staged writes and expire persistent entities."""
        self._clear_staged()
        for entity in self._identity_map.values():
            entity.__dict__["_expired"] = True
            entity.__dict__["_dirty"] = False
