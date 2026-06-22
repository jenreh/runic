"""Unit tests for the frozen domain value objects."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from runic.rag.domain import (
    Answer,
    Chunk,
    ChunkHit,
    Citation,
    EntityHit,
    ExtractedEntity,
    ExtractedRelation,
    Extraction,
    RelationHit,
    RetrievalContext,
    ScoredKey,
)


def test_chunk_is_frozen() -> None:
    chunk = Chunk(id="c1", text="hello", seq=0, source="doc.txt")
    with pytest.raises(ValidationError):
        chunk.text = "changed"  # type: ignore[misc]


def test_extracted_entity_defaults() -> None:
    entity = ExtractedEntity(name="Ada", type="Person")
    assert entity.description == ""


def test_extracted_relation_defaults() -> None:
    rel = ExtractedRelation(source="Ada", target="Babbage", rel_type="KNOWS")
    assert rel.confidence == 1.0
    assert rel.description == ""


def test_extraction_default_factories_are_independent() -> None:
    a = Extraction()
    b = Extraction()
    assert a.entities == []
    assert a.relations == []
    assert a.entities is not b.entities


def test_extraction_holds_entities_and_relations() -> None:
    extraction = Extraction(
        entities=[ExtractedEntity(name="Ada", type="Person")],
        relations=[
            ExtractedRelation(source="Ada", target="Eng", rel_type="WORKS_AT"),
        ],
    )
    assert extraction.entities[0].name == "Ada"
    assert extraction.relations[0].rel_type == "WORKS_AT"


def test_scored_key_roundtrip() -> None:
    sk = ScoredKey(key="person:ada", score=0.87)
    assert sk.key == "person:ada"
    assert sk.score == pytest.approx(0.87)


def test_entity_hit_fields() -> None:
    hit = EntityHit(
        canonical_key="person:ada",
        name="Ada",
        type="Person",
        description="pioneer",
        score=0.9,
    )
    assert hit.canonical_key == "person:ada"
    assert hit.score == pytest.approx(0.9)


def test_retrieval_context_defaults_empty() -> None:
    ctx = RetrievalContext(query="who is ada?")
    assert ctx.entities == []
    assert ctx.chunks == []
    assert ctx.relations == []


def test_answer_optional_context_and_citations() -> None:
    answer = Answer(text="Ada Lovelace.")
    assert answer.citations == []
    assert answer.context is None


def test_answer_with_full_context() -> None:
    ctx = RetrievalContext(
        query="q",
        entities=[
            EntityHit(
                canonical_key="k",
                name="n",
                type="Person",
                description="d",
                score=1.0,
            )
        ],
        chunks=[ChunkHit(id="c1", text="t", source="s", score=0.5)],
        relations=[
            RelationHit(source_key="a", target_key="b", rel_type="R", description="")
        ],
    )
    answer = Answer(
        text="answer",
        citations=[Citation(chunk_id="c1", source="s", text="t")],
        context=ctx,
    )
    assert answer.context is not None
    assert answer.context.chunks[0].id == "c1"
    assert answer.citations[0].chunk_id == "c1"


def test_value_objects_are_hashable() -> None:
    # Frozen pydantic models are hashable, enabling use in sets.
    a = ScoredKey(key="x", score=1.0)
    b = ScoredKey(key="x", score=1.0)
    assert hash(a) == hash(b)
    assert a == b
