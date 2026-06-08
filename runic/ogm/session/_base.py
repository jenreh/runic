"""Shared state and backend-agnostic behaviour for Session / AsyncSession.

:class:`_SessionBase` holds the unit-of-work bookkeeping that is identical
across the sync and async sessions — identity map, pending/deleted tracking,
entity registration, expunge, and relation-field resolution.  The two concrete
sessions inherit it and add only the ``await``-aware execution methods
(``_run_query``, ``get``, ``flush``, ``commit``, ``rollback``, the ``select()``
terminals, etc.).
"""

from __future__ import annotations

import logging
import weakref
from typing import Any

from runic.ogm.core.descriptors import FieldDescriptor, FieldInfo
from runic.ogm.core.metadata import metadata as _global_metadata
from runic.ogm.exceptions import DetachedEntityError
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.mapper.relationship_loader import RelationshipLoader
from runic.ogm.mapper.relationship_writer import RelationshipWriter

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
