"""Unit tests for the Ontology builder (no network)."""

from __future__ import annotations

from runic.rag.models import (
    Chunk,
    Entity,
    Organization,
    Person,
    RelationEdge,
)
from runic.rag.ontology import Ontology


def test_default_has_builtin_types() -> None:
    onto = Ontology.default()
    types = onto.entity_types()
    assert set(types) == {
        "Person",
        "Organization",
        "Location",
        "Concept",
        "Product",
        "Event",
    }


def test_default_subtype_for_returns_builtin_classes() -> None:
    onto = Ontology.default()
    assert onto.subtype_for("Person") is Person
    assert onto.subtype_for("Organization") is Organization


def test_subtype_for_unknown_falls_back_to_entity() -> None:
    onto = Ontology.default()
    assert onto.subtype_for("Nonexistent") is Entity


def test_schema_models_includes_entity_chunk_edge() -> None:
    onto = Ontology.default()
    models = onto.schema_models()
    assert Entity in models
    assert Chunk in models
    assert RelationEdge in models
    assert Person in models
    # No duplicates.
    assert len(models) == len(set(models))
    # Entity is first (base before subtypes).
    assert models[0] is Entity


def test_from_types_reuses_builtins_and_builds_new() -> None:
    onto = Ontology.from_types(["Person", "Company"])
    assert onto.subtype_for("Person") is Person
    company = onto.subtype_for("Company")
    assert company is not Entity
    assert issubclass(company, Entity)
    assert company._labels == ["Entity", "Company"]
    assert company._primary_label == "Entity"


def test_from_types_dynamic_subtype_constructs() -> None:
    onto = Ontology.from_types(["Company"])
    company = onto.subtype_for("Company")
    instance = company(canonical_key="company:acme", name="ACME", type="Company")
    assert instance.canonical_key == "company:acme"
    assert instance.name == "ACME"


def test_explicit_entity_models() -> None:
    onto = Ontology(entity_models=[Person, Organization])
    assert onto.entity_types() == ["Person", "Organization"]


def test_duplicate_subtype_first_wins() -> None:
    onto = Ontology(entity_models=[Person, Person])
    assert onto.entity_types() == ["Person"]


def test_repr_lists_types() -> None:
    onto = Ontology(entity_models=[Person])
    assert "Person" in repr(onto)
