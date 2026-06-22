"""Ontology — the single source of the entity-type vocabulary and OGM models.

An :class:`Ontology` bundles the set of entity-type names with their backing
OGM :class:`~runic.rag.models.Entity` subclasses. Subtypes may be supplied as
ready-made classes or built dynamically from type-name strings via the OGM
``Node`` metaclass (``labels=["Entity", T]``, ``primary_label="Entity"``).
"""

from __future__ import annotations

import logging

from runic.rag.models import (
    Chunk,
    Concept,
    Entity,
    Event,
    Location,
    Organization,
    Person,
    Product,
    RelationEdge,
)

log = logging.getLogger(__name__)

__all__ = ["Ontology"]

_DEFAULT_SUBTYPES: tuple[type[Entity], ...] = (
    Person,
    Organization,
    Location,
    Concept,
    Product,
    Event,
)


# Dynamically-built subtypes are memoised by name: each Entity subclass
# registers itself permanently in the global OGM metadata at creation, so
# repeated Ontology.from_types([...]) calls must reuse one class per name
# rather than minting (and leaking) a new registration every time.
_DYNAMIC_SUBTYPES: dict[str, type[Entity]] = {}


def _build_entity_subtype(type_name: str) -> type[Entity]:
    """Dynamically create (and memoise) an :class:`Entity` subclass for *type_name*.

    Uses the OGM ``Node`` metaclass machinery: passing ``labels`` and
    ``primary_label`` as class keywords routes through
    ``Node.__init_subclass__``, registering the new class in the OGM metadata.
    The result is cached by name so a given type yields exactly one class object.
    """
    cached = _DYNAMIC_SUBTYPES.get(type_name)
    if cached is not None:
        return cached
    subtype = type(
        type_name,
        (Entity,),
        {"__module__": __name__, "__doc__": f"Dynamic entity subtype: {type_name}."},
        labels=["Entity", type_name],
        primary_label="Entity",
    )
    _DYNAMIC_SUBTYPES[type_name] = subtype
    return subtype


class Ontology:
    """The entity-type vocabulary plus its OGM model classes.

    Construct directly with explicit subclasses, or use :meth:`default` /
    :meth:`from_types`. The ontology never duplicates a type name; the first
    model registered for a given subtype label wins.
    """

    def __init__(self, entity_models: list[type[Entity]] | None = None) -> None:
        self._subtypes: dict[str, type[Entity]] = {}
        for model in entity_models or []:
            self._register(model)

    # ── Construction helpers ────────────────────────────────────────────────

    @classmethod
    def default(cls) -> Ontology:
        """Return an ontology with the generic built-in entity subtypes."""
        return cls(entity_models=list(_DEFAULT_SUBTYPES))

    @classmethod
    def from_types(cls, type_names: list[str]) -> Ontology:
        """Build an ontology by dynamically creating subtypes for *type_names*.

        Existing built-in subtypes (Person, Organization, ...) are reused when
        their name matches; otherwise a new subclass is generated.
        """
        builtin = {m.__name__: m for m in _DEFAULT_SUBTYPES}
        models: list[type[Entity]] = []
        for name in type_names:
            model = builtin.get(name) or _build_entity_subtype(name)
            models.append(model)
        return cls(entity_models=models)

    # ── Introspection ───────────────────────────────────────────────────────

    def entity_types(self) -> list[str]:
        """Return the ordered list of entity-type names in this ontology."""
        return list(self._subtypes.keys())

    def subtype_for(self, type: str) -> type[Entity]:  # noqa: A002
        """Return the :class:`Entity` subclass for *type*.

        Falls back to the base :class:`Entity` class for unknown type names so
        extraction of an unmodelled type still persists as a generic entity.
        """
        return self._subtypes.get(type, Entity)

    def schema_models(self) -> list[type]:
        """Return all OGM model classes required to bootstrap this ontology.

        Includes the base :class:`Entity`, every subtype, the :class:`Chunk`
        node, and the :class:`RelationEdge` — deduplicated, base-first.
        """
        models: list[type] = [Entity]
        models.extend(self._subtypes.values())
        models.append(Chunk)
        models.append(RelationEdge)
        # Dedupe while preserving order.
        seen: set[type] = set()
        result: list[type] = []
        for model in models:
            if model not in seen:
                seen.add(model)
                result.append(model)
        return result

    # ── Internals ───────────────────────────────────────────────────────────

    def _register(self, model: type[Entity]) -> None:
        subtype_label = self._subtype_label(model)
        if subtype_label in self._subtypes:
            log.debug("Subtype %s already registered; keeping first.", subtype_label)
            return
        self._subtypes[subtype_label] = model

    @staticmethod
    def _subtype_label(model: type[Entity]) -> str:
        """Derive the subtype name (the non-base label, else the class name)."""
        labels: list[str] = getattr(model, "_labels", [model.__name__])
        for label in labels:
            if label != "Entity":
                return label
        return model.__name__

    def __repr__(self) -> str:
        return f"Ontology(types={self.entity_types()!r})"
