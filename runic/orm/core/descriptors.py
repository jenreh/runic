"""Field and Relation descriptors for graph entity properties and relationships."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, overload

if TYPE_CHECKING:
    from runic.orm.core.types import TypeConverter

log = logging.getLogger(__name__)


class _NotLoadedType:
    """Singleton sentinel for lazy relationship fields not yet loaded from the graph."""

    _instance: _NotLoadedType | None = None

    def __new__(cls) -> _NotLoadedType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "_NOT_LOADED"

    def __bool__(self) -> bool:
        return False


_NOT_LOADED: _NotLoadedType = _NotLoadedType()


class _MissingType:
    """Singleton sentinel for fields that have no default value."""

    _instance: _MissingType | None = None

    def __new__(cls) -> _MissingType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: _MissingType = _MissingType()


class FieldDescriptor:
    """Descriptor backing both Field() and Relation() declarations.

    Behaves as a data descriptor: values are stored per-instance in ``__dict__``.
    Writing to an instance attribute via this descriptor sets ``instance._dirty = True``,
    which the Mapper uses to detect changes on persistent entities.

    Query expression operators
    --------------------------
    When accessed at the **class level** (``User.name``, ``Rated.score``),
    the descriptor returns itself.  The comparison operators defined below
    produce :class:`~runic.orm.query.expressions.FilterExpr` objects for use
    with :meth:`~runic.orm.query.builder.QueryBuilder.where`:

    .. code-block:: python

        session.query(User).where(User.name == "Alice")
        session.query(User).where(User.age > 18)
        session.query(User).where(User.bio.contains("graph"))
        session.query(User).where(User.deleted_at.is_null())

    ``__hash__`` is kept as ``object.__hash__`` so descriptors remain
    hashable and can appear in sets/dicts used internally.
    """

    def __init__(
        self,
        *,
        default: Any = MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
        kw_only: bool = True,
        # Property options
        index: bool = False,
        index_type: Literal["FULLTEXT", "VECTOR"] | None = None,
        unique: bool = False,
        required: bool = False,
        primary_key: bool = False,
        # Relationship options (set only by Relation())
        relationship: str | None = None,
        direction: Literal["OUTGOING", "INCOMING", "BOTH"] | None = None,
        target: str | type | None = None,
        edge_model: str | type | None = None,
        cascade: bool = False,
        lazy: bool = True,
        # Misc
        converter: TypeConverter | None = None,
        generated: bool = False,
        interned: bool = False,
    ) -> None:
        if default is not MISSING and default_factory is not None:
            raise ValueError("Cannot specify both 'default' and 'default_factory'.")

        if relationship is not None:
            if index or unique:
                raise ValueError(
                    "Relationship fields cannot have 'index' or 'unique' constraints."
                )
            if target is None:
                raise ValueError("Relationship fields must specify 'target'.")
            if default is MISSING and default_factory is None:
                default = None

        if generated and default is MISSING and default_factory is None:
            default = None

        self.default = default
        self.default_factory = default_factory
        self.init = init
        self.kw_only = kw_only
        self.index = index
        self.index_type = index_type
        self.unique = unique
        self.required = required
        self.primary_key = primary_key
        self.relationship = relationship
        self.direction = direction
        self.target = target
        self.edge_model = edge_model
        self.cascade = cascade
        self.lazy = lazy
        self.converter = converter
        self.generated = generated
        self.interned = interned
        self._name: str = ""
        self._owner: type | None = None

    # ------------------------------------------------------------------
    # Descriptor protocol
    # ------------------------------------------------------------------

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name
        self._owner = owner

    @property
    def name(self) -> str:
        """Public read-only accessor for the attribute name set by ``__set_name__``."""
        return self._name

    @overload
    def __get__(self, obj: None, objtype: type | None = ...) -> FieldDescriptor: ...

    @overload
    def __get__(self, obj: object, objtype: type | None = ...) -> Any: ...

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        try:
            val = obj.__dict__[self._name]
        except KeyError:
            if self.has_default:
                return self.get_default()
            raise AttributeError(
                f"'{type(obj).__name__}' has no value for field '{self._name}'"
            ) from None
        if val is _NOT_LOADED:
            return self._trigger_lazy_load(obj)
        return val

    def _trigger_lazy_load(self, obj: Any) -> Any:
        """Trigger lazy loading of this relationship field on *obj* via the active session."""
        import weakref

        session_ref = obj.__dict__.get("_session")
        if session_ref is None:
            from runic.orm.exceptions import DetachedEntityError

            raise DetachedEntityError(
                f"Entity {obj!r} has no active session. "
                f"Load via session.get() or use fetch=[{self._name!r}] for eager loading."
            )
        session = session_ref() if isinstance(session_ref, weakref.ref) else session_ref
        if session is None:
            from runic.orm.exceptions import DetachedEntityError

            raise DetachedEntityError(
                f"Entity {obj!r}'s session was garbage-collected. "
                f"Use fetch=[{self._name!r}] for eager loading."
            )
        return session.load_relationship(obj, self._name)

    def __set__(self, obj: Any, value: Any) -> None:
        obj.__dict__[self._name] = value
        obj.__dict__["_dirty"] = True

    # ------------------------------------------------------------------
    # Default helpers
    # ------------------------------------------------------------------

    @property
    def has_default(self) -> bool:
        """True if a default value or factory is configured."""
        return self.default is not MISSING or self.default_factory is not None

    def get_default(self) -> Any:
        """Return the default value, calling ``default_factory`` if set."""
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not MISSING:
            return self.default
        raise ValueError(f"Field '{self._name}' has no default value.")

    @property
    def field_name(self) -> str:
        """Public accessor for the descriptor's attribute name."""
        return self._name

    @property
    def owner(self) -> type | None:
        """Public accessor for the class that owns this descriptor."""
        return self._owner

    def __repr__(self) -> str:
        parts: list[str] = [f"name={self._name!r}"]
        if self.default is not MISSING:
            parts.append(f"default={self.default!r}")
        if self.relationship:
            parts.append(f"relationship={self.relationship!r}")
        return f"FieldDescriptor({', '.join(parts)})"

    # ------------------------------------------------------------------
    # Query expression operators (class-level access only)
    #
    # These return FilterExpr objects used by QueryBuilder.where().
    # They are only meaningful when the descriptor is accessed at the
    # class level (obj is None), which is the case in:
    #     User.name == "Alice"   → FilterExpr(cls=User, prop="name", op="=", ...)
    #
    # __hash__ is kept as object.__hash__ so descriptors remain hashable.
    # ------------------------------------------------------------------

    __hash__ = object.__hash__  # type: ignore[assignment]

    def _make_filter(self, op: str, value: Any, negate: bool = False) -> Any:
        from runic.orm.query.expressions import FilterExpr

        return FilterExpr(
            cls=self._owner or type(self),
            prop=self._name,
            op=op,
            value=value,
            negate=negate,
        )

    def __eq__(self, other: object) -> Any:  # type: ignore[override]
        if other is None:
            return self._make_filter("IS NULL", None)
        return self._make_filter("=", other)

    def __ne__(self, other: object) -> Any:  # type: ignore[override]
        if other is None:
            return self._make_filter("IS NOT NULL", None)
        return self._make_filter("<>", other)

    def __gt__(self, other: Any) -> Any:
        return self._make_filter(">", other)

    def __ge__(self, other: Any) -> Any:
        return self._make_filter(">=", other)

    def __lt__(self, other: Any) -> Any:
        return self._make_filter("<", other)

    def __le__(self, other: Any) -> Any:
        return self._make_filter("<=", other)

    # String predicates -------------------------------------------------

    def contains(self, value: str) -> Any:
        """Return a ``CONTAINS`` filter: ``prop CONTAINS $value``."""
        return self._make_filter("CONTAINS", value)

    def startswith(self, value: str) -> Any:
        """Return a ``STARTS WITH`` filter: ``prop STARTS WITH $value``."""
        return self._make_filter("STARTS WITH", value)

    def endswith(self, value: str) -> Any:
        """Return an ``ENDS WITH`` filter: ``prop ENDS WITH $value``."""
        return self._make_filter("ENDS WITH", value)

    def matches(self, pattern: str) -> Any:
        """Return a regex filter: ``prop =~ $pattern``."""
        return self._make_filter("=~", pattern)

    # Null checks -------------------------------------------------------

    def is_null(self) -> Any:
        """Return an ``IS NULL`` filter."""
        return self._make_filter("IS NULL", None)

    def is_not_null(self) -> Any:
        """Return an ``IS NOT NULL`` filter."""
        return self._make_filter("IS NOT NULL", None)

    # List membership ---------------------------------------------------

    def in_(self, values: list[Any]) -> Any:
        """Return an ``IN`` filter: ``prop IN $values``."""
        return self._make_filter("IN", values)

    def not_in_(self, values: list[Any]) -> Any:
        """Return a ``NOT IN`` filter: ``NOT prop IN $values``."""
        return self._make_filter("IN", values, negate=True)


class FieldInfo:
    """Pairs a field name with its FieldDescriptor; used during __init__ generation."""

    __slots__ = ("field", "is_collection", "name")

    def __init__(
        self, name: str, field: FieldDescriptor, is_collection: bool = False
    ) -> None:
        self.name = name
        self.field = field
        self.is_collection = is_collection

    def __repr__(self) -> str:
        return f"FieldInfo(name={self.name!r}, field={self.field!r})"


def Field(  # noqa: N802
    *,
    default: Any = MISSING,
    default_factory: Callable[[], Any] | None = None,
    init: bool = True,
    kw_only: bool = True,
    index: bool = False,
    index_type: Literal["FULLTEXT", "VECTOR"] | None = None,
    unique: bool = False,
    required: bool = False,
    primary_key: bool = False,
    converter: TypeConverter | None = None,
    generated: bool = False,
    interned: bool = False,
) -> Any:
    """Declare a property field on a Node or Edge.

    Returns a :class:`FieldDescriptor` typed as ``Any`` so that
    ``name: str = Field()`` is accepted by type checkers without error.

    Set ``interned=True`` to store the value via FalkorDB's ``intern()`` function,
    which deduplicates repeated strings (e.g. country names, status codes, tags)
    by keeping a single shared copy in the database.

    Example::

        class Person(Node, labels=["Person"]):
            id: str = Field(primary_key=True)
            name: str = Field()
            age: int | None = Field(default=None)
            country: str = Field(interned=True)
            email: str = Field(index=True, unique=True)
    """
    return FieldDescriptor(
        default=default,
        default_factory=default_factory,
        init=init,
        kw_only=kw_only,
        index=index,
        index_type=index_type,
        unique=unique,
        required=required,
        primary_key=primary_key,
        converter=converter,
        generated=generated,
        interned=interned,
    )


def Relation(  # noqa: N802
    *,
    relationship: str,
    direction: Literal["OUTGOING", "INCOMING", "BOTH"],
    target: str | type,
    edge_model: str | type | None = None,
    cascade: bool = False,
    lazy: bool = True,
    default: Any = None,
    default_factory: Callable[[], Any] | None = None,
    init: bool = True,
) -> Any:
    """Declare a relationship field on a Node.

    Returns a :class:`FieldDescriptor` typed as ``Any`` so that
    ``company: Company | None = Relation(...)`` is accepted by type checkers.

    Example::

        class Person(Node, labels=["Person"]):
            id: str = Field()
            company: Company | None = Relation(
                relationship="WORKS_FOR",
                direction="OUTGOING",
                target="Company",
            )
            friends: list["Person"] = Relation(
                relationship="KNOWS",
                direction="OUTGOING",
                target="Person",
            )
    """
    return FieldDescriptor(
        relationship=relationship,
        direction=direction,
        target=target,
        edge_model=edge_model,
        cascade=cascade,
        lazy=lazy,
        default=default,
        default_factory=default_factory,
        init=init,
    )
