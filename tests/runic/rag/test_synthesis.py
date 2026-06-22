"""Unit tests for :class:`runic.rag.adapters.synthesis.PydanticAISynthesizer`.

All tests are network-free: the real pydantic-ai agent is swapped for one
driven by :class:`~pydantic_ai.models.test.TestModel` or
:class:`~pydantic_ai.models.function.FunctionModel` via monkeypatching the
module-level ``build_agent`` factory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

import runic.rag.adapters.synthesis as synthesis_module
from runic.rag.adapters.synthesis import PydanticAISynthesizer
from runic.rag.concurrency import BudgetGuard
from runic.rag.domain import (
    Answer,
    ChunkHit,
    EntityHit,
    RelationHit,
    RetrievalContext,
)
from runic.rag.exceptions import BudgetExceededError

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from runic.rag.config import RagSettings


def _context(query: str = "Who founded ACME?") -> RetrievalContext:
    """A small context with entities, relations, and two source chunks."""
    return RetrievalContext(
        query=query,
        entities=[
            EntityHit(
                canonical_key="person:jane",
                name="Jane Doe",
                type="Person",
                description="Founder of ACME.",
                score=0.91,
            ),
            EntityHit(
                canonical_key="org:acme",
                name="ACME",
                type="Organization",
                description="",
                score=0.80,
            ),
        ],
        relations=[
            RelationHit(
                source_key="person:jane",
                target_key="org:acme",
                rel_type="FOUNDED",
                description="in 1999",
            )
        ],
        chunks=[
            ChunkHit(
                id="c1",
                text="Jane Doe founded ACME in 1999.",
                source="doc-a",
                score=0.95,
            ),
            ChunkHit(
                id="c2",
                text="ACME is headquartered in Berlin.",
                source="doc-b",
                score=0.70,
            ),
        ],
    )


def _patch_agent(
    monkeypatch: pytest.MonkeyPatch,
    *,
    model: TestModel | FunctionModel,
) -> list[str]:
    """Patch ``build_agent`` to return a *model*-driven agent; record prompts.

    Returns a list that captures the user prompt passed to each ``run_sync``.
    """
    captured: list[str] = []

    def fake_build_agent(
        settings: RagSettings, *, output_type: object = None, system_prompt: str
    ) -> Agent[None, str]:
        agent: Agent[None, str] = Agent(model, system_prompt=system_prompt)
        original_run = agent.run_sync

        def run_sync(user_prompt: str) -> object:
            captured.append(user_prompt)
            return original_run(user_prompt)

        monkeypatch.setattr(agent, "run_sync", run_sync)
        return agent

    monkeypatch.setattr(synthesis_module, "build_agent", fake_build_agent)
    return captured


def test_synthesize_populates_text_and_citations(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """A fixed-output model yields the text and one citation per chunk."""
    _patch_agent(monkeypatch, model=TestModel(custom_output_text="Jane Doe [chunk:c1]"))
    synth = PydanticAISynthesizer(rag_settings)

    answer = synth.synthesize("Who founded ACME?", _context())

    assert isinstance(answer, Answer)
    assert answer.text == "Jane Doe [chunk:c1]"
    assert [c.chunk_id for c in answer.citations] == ["c1", "c2"]
    assert {c.source for c in answer.citations} == {"doc-a", "doc-b"}
    assert answer.citations[0].text == "Jane Doe founded ACME in 1999."
    # The originating context is round-tripped onto the answer.
    assert answer.context is not None
    assert answer.context.query == "Who founded ACME?"


def test_prompt_contains_grounding(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """The prompt sent to the LLM embeds entities, relations, and chunk ids."""
    captured = _patch_agent(monkeypatch, model=TestModel(custom_output_text="ok"))
    synth = PydanticAISynthesizer(rag_settings)

    synth.synthesize("Who founded ACME?", _context())

    assert len(captured) == 1
    prompt = captured[0]
    assert "Question: Who founded ACME?" in prompt
    assert "Jane Doe (Person)" in prompt
    assert "Founder of ACME." in prompt
    assert "person:jane -[FOUNDED]-> org:acme" in prompt
    assert "[chunk:c1]" in prompt
    assert "[chunk:c2]" in prompt
    assert "Jane Doe founded ACME in 1999." in prompt


def test_synthesize_uses_function_model_over_query(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """A FunctionModel can derive the answer from the prompt deterministically."""

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:  # noqa: ARG001
        user_text = str(getattr(messages[-1].parts[-1], "content", ""))
        answer = "FOUNDER FOUND" if "FOUNDED" in user_text else "unknown"
        return ModelResponse(parts=[TextPart(answer)])

    _patch_agent(monkeypatch, model=FunctionModel(fn))
    synth = PydanticAISynthesizer(rag_settings)

    answer = synth.synthesize("Who founded ACME?", _context())

    assert answer.text == "FOUNDER FOUND"
    assert len(answer.citations) == 2


def test_empty_context_still_answers(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """With no chunks the synthesizer still returns an Answer (no citations)."""
    captured = _patch_agent(
        monkeypatch, model=TestModel(custom_output_text="I don't know.")
    )
    synth = PydanticAISynthesizer(rag_settings)

    answer = synth.synthesize("anything?", RetrievalContext(query="anything?"))

    assert answer.text == "I don't know."
    assert answer.citations == []
    assert "No supporting context" in captured[0]


def test_citations_dedupe_repeated_chunk_ids(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """Repeated chunk ids in the context collapse to a single citation."""
    _patch_agent(monkeypatch, model=TestModel(custom_output_text="x"))
    synth = PydanticAISynthesizer(rag_settings)
    chunk = ChunkHit(id="dup", text="t", source="s", score=0.5)
    context = RetrievalContext(query="q", chunks=[chunk, chunk])

    answer = synth.synthesize("q", context)

    assert [c.chunk_id for c in answer.citations] == ["dup"]


def test_budget_guard_records_one_call(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """A successful synthesis records exactly one LLM call on the guard."""
    _patch_agent(monkeypatch, model=TestModel(custom_output_text="ok"))
    guard = BudgetGuard(max_llm_calls=5)
    synth = PydanticAISynthesizer(rag_settings, budget=guard)

    synth.synthesize("q", _context())

    assert guard.llm_calls == 1


def test_budget_guard_blocks_when_exhausted(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """An exhausted budget raises before the (patched) agent is ever built."""
    built: list[bool] = []

    def fake_build_agent(*args: object, **kwargs: object) -> Agent[None, str]:
        built.append(True)
        raise AssertionError("agent must not be built once budget is exhausted")

    monkeypatch.setattr(synthesis_module, "build_agent", fake_build_agent)
    guard = BudgetGuard(max_llm_calls=1)
    guard.record(llm_calls=1)
    synth = PydanticAISynthesizer(rag_settings, budget=guard)

    with pytest.raises(BudgetExceededError):
        synth.synthesize("q", _context())
    assert built == []
