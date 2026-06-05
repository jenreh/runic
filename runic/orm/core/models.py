"""Node and Edge base classes for graph entities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, ClassVar, dataclass_transform

from runic.orm.core.descriptors import Field, FieldInfo

log = logging.getLogger(__name__)

# Marker stored on the base classes so _collect_fields can skip them.
_BASE_CLASS_MARKER = "_is_orm_base"


def _is_collection_annotation(ann: Any) -> bool:
    """Return True if *ann* represents a list/collection type."""
    if isinstance(ann, str):
        return ann.startswith(("list[", "List["))
    # Python 3.9+ generic alias: list[X] or typing.List[X]
    origin = getattr(ann, "__origin__", None)
    if origin is list:
        return True
    try:
        import typing

        return typing.get_origin(ann) is list
    except Exception:
        return False


_ABSENT = object()


def _synthesize_plain_annotations(cls: type) -> None:
    """Install Field descriptors for bare ``name: type`` annotations on *cls*.

    Called before ``_collect_fields`` so plain annotations participate in
    dirty-tracking and ``__init__`` generation identically to explicit
    ``Field()`` declarations.  Only annotations declared directly on *cls*
    (not inherited ones) are processed; ancestors handle their own during
    their own ``__init_subclass__`` call.
    """
    for name, ann in cls.__annotations__.items():
        if name.startswith("_"):
            continue
        ann_str = ann if isinstance(ann, str) else repr(ann)
        if "ClassVar" in ann_str:
            continue
        if isinstance(cls.__dict__.get(name), Field):
            continue
        val = cls.__dict__.get(name, _ABSENT)
        if val is _ABSENT:
            field = Field()
        else:
            field = Field(default=val)
        field.__set_name__(cls, name)
        setattr(cls, name, field)


def _collect_fields(cls: type, stop_at: type) -> list[FieldInfo]:
    """Collect Field descriptors from *cls* and its ancestors.

    Traverses the MRO in reverse (most-base first) so that parent fields come
    before child fields in the returned list.  ``stop_at`` (Node or Edge) and
    ``object`` are excluded.  If a name appears in multiple bases the first
    occurrence wins (i.e. parent definition is kept; child cannot shadow).

    ``FieldInfo.is_collection`` is set from the type annotation — ``True`` when
    the annotation is ``list[...]`` or ``List[...]``.
    """
    # Merge annotations across MRO so child overrides are handled correctly.
    annotations: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        if base is object or base is stop_at:
            continue
        annotations.update(getattr(base, "__annotations__", {}))

    seen: set[str] = set()
    result: list[FieldInfo] = []
    for base in reversed(cls.__mro__):
        if base is object or base is stop_at:
            continue
        for name, val in base.__dict__.items():
            if isinstance(val, Field) and name not in seen:
                ann = annotations.get(name)
                is_coll = _is_collection_annotation(ann)
                result.append(FieldInfo(name=name, field=val, is_collection=is_coll))
                seen.add(name)
    return result


def _make_init(field_infos: list[FieldInfo]) -> Callable[..., None]:
    """Return a ``__init__`` function that accepts all *field_infos* as kwargs.

    Values are stored directly into ``instance.__dict__`` to bypass
    ``Field.__set__``, preventing the initial construction from marking
    the entity dirty.
    """
    init_fields = [fi for fi in field_infos if fi.field.init]
    non_init_fields = [fi for fi in field_infos if not fi.field.init]
    required_names = frozenset(
        fi.name for fi in init_fields if not fi.field.has_default
    )
    init_names = frozenset(fi.name for fi in init_fields)

    def _generated_init(instance: Any, **kwargs: Any) -> None:
        # Reject unknown keyword arguments.
        for key in kwargs:
            if key not in init_names:
                raise TypeError(f"__init__() got unexpected keyword argument '{key!r}'")

        # Enforce required fields.
        for name in required_names:
            if name not in kwargs:
                raise TypeError(
                    f"__init__() missing required keyword argument: '{name}'"
                )

        # Object-state flags — written directly to bypass Field.__set__.
        instance.__dict__["_new"] = True
        instance.__dict__["_dirty"] = False

        # Initialise declared init fields.
        for fi in init_fields:
            if fi.name in kwargs:
                instance.__dict__[fi.name] = kwargs[fi.name]
            else:
                instance.__dict__[fi.name] = fi.field.get_default()

        # Initialise non-init fields from their defaults.
        for fi in non_init_fields:
            if fi.field.has_default:
                instance.__dict__[fi.name] = fi.field.get_default()

    return _generated_init


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@dataclass_transform(field_specifiers=(Field,), kw_only_default=True)
class Node:
    """Base class for graph nodes.

    Subclass with ``labels`` and optional ``primary_label`` class keywords::

        class Country(
            Location, labels=["Location", "Country"], primary_label="Location"
        ):
            iso_code: str = Field(unique=True)

    ``__init__`` is generated automatically from declared ``Field`` descriptors.
    Setting any field on an existing instance marks it dirty (``_dirty = True``),
    which the Mapper interprets as a MERGE/SET on the next flush.
    """

    _is_orm_base: ClassVar[bool] = True

    # Class-level attributes set by __init_subclass__:
    _labels: ClassVar[list[str]]
    _primary_label: ClassVar[str]
    _fields: ClassVar[list[FieldInfo]]

    # Instance-level state flags (written by _make_init / Mapper):
    _new: bool
    _dirty: bool

    def __init_subclass__(
        cls,
        labels: list[str] | None = None,
        primary_label: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)

        effective_labels = labels if labels is not None else [cls.__name__]
        effective_primary = (
            primary_label if primary_label is not None else effective_labels[0]
        )

        cls._labels = effective_labels
        cls._primary_label = effective_primary
        _synthesize_plain_annotations(cls)
        cls._fields = _collect_fields(cls, Node)
        cls.__init__ = _make_init(cls._fields)  # type: ignore[method-assign]

        from runic.orm.core.metadata import metadata

        metadata.register_node(cls)
        log.debug("Node subclass registered: %s", cls.__name__)

    def __repr__(self) -> str:
        pk_field = next(
            (
                fi
                for fi in self.__class__._fields
                if fi.field.primary_key or fi.name == "id"
            ),
            None,
        )
        if pk_field:
            pk_val = self.__dict__.get(pk_field.name, "?")
            return f"{type(self).__name__}({pk_field.name}={pk_val!r})"
        return f"{type(self).__name__}()"


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------


@dataclass_transform(field_specifiers=(Field,), kw_only_default=True)
class Edge:
    """Base class for graph edge property models.

    Subclass with a ``type`` class keyword::

        class InvitationEdge(Edge, type="INVITED_TO"):
            role: str = Field(required=True)

    Edge instances carry the same ``_new``/``_dirty`` lifecycle flags as Node.
    """

    _is_orm_base: ClassVar[bool] = True

    # Class-level attributes set by __init_subclass__:
    _edge_type: ClassVar[str]
    _fields: ClassVar[list[FieldInfo]]

    # Instance-level state flags:
    _new: bool
    _dirty: bool

    def __init_subclass__(
        cls,
        type: str | None = None,  # noqa: A002
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)

        cls._edge_type = type if type is not None else cls.__name__
        _synthesize_plain_annotations(cls)
        cls._fields = _collect_fields(cls, Edge)
        cls.__init__ = _make_init(cls._fields)  # type: ignore[method-assign]

        from runic.orm.core.metadata import metadata

        metadata.register_edge(cls)
        log.debug("Edge subclass registered: %s", cls.__name__)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(type={self._edge_type!r})"
