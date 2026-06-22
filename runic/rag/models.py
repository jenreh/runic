"""OGM node and edge models for the runic.rag knowledge graph.

These map directly onto graph nodes/edges via :mod:`runic.ogm`. Embedding
fields are typed ``Vector | None`` (DE-RISKED FACT 1): on FalkorDB this drives
``vecf32()`` so the KNN index works; other backends store a raw list.

The labels here (``Entity``, ``Chunk``) and edge types (``RELATES_TO``,
``MENTIONS``) form the canonical RAG schema that :mod:`runic.rag.ontology`
extends with dynamic subtypes.
"""

from __future__ import annotations

from runic.ogm import Edge, Field, Node, Relation, Vector

__all__ = [
    "Chunk",
    "Concept",
    "Entity",
    "Event",
    "Location",
    "Organization",
    "Person",
    "Product",
    "RelationEdge",
]


class RelationEdge(Edge, type="RELATES_TO"):
    """Property model for a typed relation between two entities."""

    rel_type: str = Field(index=True)
    description: str = Field(default="")
    confidence: float = Field(default=1.0)
    source_chunk: str = Field(default="")


class Entity(Node, labels=["Entity"], primary_label="Entity"):
    """A canonical knowledge-graph entity.

    ``canonical_key`` is the primary key; ``name`` and ``description`` are
    fulltext-indexed; ``embedding`` backs the vector index.
    """

    canonical_key: str = Field(primary_key=True)
    name: str = Field(index_type="FULLTEXT")
    type: str = Field(index=True)
    description: str = Field(default="", index_type="FULLTEXT")
    embedding: Vector | None = Field(default=None, index_type="VECTOR")

    related: list[Entity] = Relation(
        relationship="RELATES_TO",
        direction="OUTGOING",
        target="Entity",
        edge_model=RelationEdge,
    )


class Chunk(Node, labels=["Chunk"], primary_label="Chunk"):
    """A persisted source-text chunk and the entities it mentions."""

    id: str = Field(primary_key=True)
    text: str = Field(index_type="FULLTEXT")
    source: str = Field(index=True)
    seq: int = Field(default=0)
    embedding: Vector | None = Field(default=None, index_type="VECTOR")

    mentions: list[Entity] = Relation(
        relationship="MENTIONS",
        direction="OUTGOING",
        target="Entity",
    )


class Person(Entity, labels=["Entity", "Person"], primary_label="Entity"):
    """A person entity subtype."""


class Organization(Entity, labels=["Entity", "Organization"], primary_label="Entity"):
    """An organization entity subtype."""


class Location(Entity, labels=["Entity", "Location"], primary_label="Entity"):
    """A location entity subtype."""


class Concept(Entity, labels=["Entity", "Concept"], primary_label="Entity"):
    """A concept entity subtype."""


class Product(Entity, labels=["Entity", "Product"], primary_label="Entity"):
    """A product entity subtype."""


class Event(Entity, labels=["Entity", "Event"], primary_label="Entity"):
    """An event entity subtype."""
