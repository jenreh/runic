"""Unit tests for runic.migrate.manifest dataclasses."""

from __future__ import annotations

from runic.migrate.manifest import (
    FulltextIndex,
    MandatoryConstraint,
    RangeIndex,
    SchemaManifest,
    UniqueConstraint,
    VectorIndex,
)


def test_schema_manifest_defaults() -> None:
    m = SchemaManifest()
    assert m.range_indexes == []
    assert m.fulltext_indexes == []
    assert m.vector_indexes == []
    assert m.constraints == []


def test_range_index_eq() -> None:
    a = RangeIndex("Person", "email")
    b = RangeIndex("Person", "email")
    assert a == b


def test_range_index_rel_flag() -> None:
    node = RangeIndex("Person", "email")
    rel = RangeIndex("Person", "email", rel=True)
    assert node != rel


def test_fulltext_index_props_tuple() -> None:
    idx = FulltextIndex("Movie", ["title", "body"])
    assert idx.props == ("title", "body")


def test_fulltext_index_eq() -> None:
    a = FulltextIndex("Movie", ["title"])
    b = FulltextIndex("Movie", ["title"])
    assert a == b


def test_vector_index_defaults() -> None:
    idx = VectorIndex("Doc", "embedding", 128, "cosine")
    assert idx.m == 16
    assert idx.ef_construction == 200
    assert idx.ef_runtime == 10


def test_unique_constraint_props_tuple() -> None:
    c = UniqueConstraint("NODE", "User", ["id", "email"])
    assert c.props == ("id", "email")


def test_mandatory_constraint_eq() -> None:
    a = MandatoryConstraint("NODE", "Person", ["name"])
    b = MandatoryConstraint("NODE", "Person", ["name"])
    assert a == b


def test_schema_manifest_with_values() -> None:
    m = SchemaManifest(
        range_indexes=[RangeIndex("Person", "email")],
        constraints=[UniqueConstraint("NODE", "Person", ["email"])],
    )
    assert len(m.range_indexes) == 1
    assert len(m.constraints) == 1
