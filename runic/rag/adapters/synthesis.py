"""LLM answer synthesis for runic.rag (the :class:`Synthesizer` port).

:class:`PydanticAISynthesizer` turns a
:class:`~runic.rag.domain.RetrievalContext` into a grounded
:class:`~runic.rag.domain.Answer`. It renders the retrieved entities,
relations, and chunk texts (each tagged with its chunk id) into a single
prompt, asks a pydantic-ai :class:`~pydantic_ai.Agent` for a plain-text answer
that cites those ids, and attaches a :class:`~runic.rag.domain.Citation` for
every chunk that fed the prompt.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from runic.rag.adapters._llm import build_agent
from runic.rag.concurrency import estimate_tokens
from runic.rag.domain import Answer, Citation, RetrievalContext

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from runic.rag.concurrency import BudgetGuard
    from runic.rag.config import RagSettings

log = logging.getLogger(__name__)

__all__ = ["PydanticAISynthesizer"]

_SYSTEM_PROMPT = (
    "You are a precise question-answering assistant for a knowledge graph. "
    "Answer the user's question using ONLY the supplied context (entities, "
    "relations, and source passages). Each passage is tagged with a chunk id "
    "like [chunk:ID]; cite the ids you rely on inline using that exact "
    "notation. If the context does not contain the answer, say so plainly "
    "instead of guessing."
)

_NO_CONTEXT = "No supporting context was retrieved for this question."


class PydanticAISynthesizer:
    """Synthesizer backed by a pydantic-ai agent over an OpenAI-compatible LLM.

    Args:
        settings: Runtime configuration used to build the chat model/agent.
        budget: Optional cost guard; one LLM call is recorded per synthesis,
            so an exhausted budget raises before any network request is made.
    """

    def __init__(
        self,
        settings: RagSettings,
        *,
        budget: BudgetGuard | None = None,
    ) -> None:
        self._settings = settings
        self._budget = budget

    def synthesize(self, query: str, context: RetrievalContext) -> Answer:
        """Return a cited :class:`Answer` for *query* grounded in *context*."""
        # Pre-flight: fail before the network call if the budget is exhausted;
        # the actual usage is recorded only after a successful call below.
        if self._budget is not None:
            self._budget.check()

        prompt = self._build_prompt(query, context)
        agent = self._build_agent()
        result = agent.run_sync(prompt)
        text = str(result.output).strip()

        if self._budget is not None:
            self._budget.record(
                llm_calls=1, tokens=estimate_tokens(prompt) + estimate_tokens(text)
            )

        citations = self._citations_for(context)
        log.debug(
            "Synthesized answer (%d chars) with %d citation(s)",
            len(text),
            len(citations),
        )
        return Answer(text=text, citations=citations, context=context)

    def _build_agent(self) -> Agent[None, str]:
        """Construct a plain-text agent for synthesis."""
        return build_agent(
            self._settings,
            output_type=None,
            system_prompt=_SYSTEM_PROMPT,
        )

    @staticmethod
    def _citations_for(context: RetrievalContext) -> list[Citation]:
        """Build one citation per context chunk, preserving order/uniqueness."""
        citations: list[Citation] = []
        seen: set[str] = set()
        for chunk in context.chunks:
            if chunk.id in seen:
                continue
            seen.add(chunk.id)
            citations.append(
                Citation(chunk_id=chunk.id, source=chunk.source, text=chunk.text)
            )
        return citations

    @staticmethod
    def _build_prompt(query: str, context: RetrievalContext) -> str:
        """Render *query* and *context* into a single grounded user prompt."""
        sections: list[str] = [f"Question: {query}", ""]

        entities = PydanticAISynthesizer._render_entities(context)
        if entities:
            sections.append(entities)
            sections.append("")

        relations = PydanticAISynthesizer._render_relations(context)
        if relations:
            sections.append(relations)
            sections.append("")

        passages = PydanticAISynthesizer._render_chunks(context)
        sections.append(passages if passages else _NO_CONTEXT)
        sections.append("")
        sections.append(
            "Answer the question grounded in the passages above, citing the "
            "relevant [chunk:ID] tags."
        )
        return "\n".join(sections)

    @staticmethod
    def _render_entities(context: RetrievalContext) -> str:
        """Render the entity block, or an empty string when there are none."""
        if not context.entities:
            return ""
        lines = ["Entities:"]
        for entity in context.entities:
            detail = f" — {entity.description}" if entity.description else ""
            lines.append(f"- {entity.name} ({entity.type}){detail}")
        return "\n".join(lines)

    @staticmethod
    def _render_relations(context: RetrievalContext) -> str:
        """Render the relation block, or an empty string when there are none."""
        if not context.relations:
            return ""
        lines = ["Relations:"]
        for relation in context.relations:
            detail = f" — {relation.description}" if relation.description else ""
            lines.append(
                f"- {relation.source_key} -[{relation.rel_type}]-> "
                f"{relation.target_key}{detail}"
            )
        return "\n".join(lines)

    @staticmethod
    def _render_chunks(context: RetrievalContext) -> str:
        """Render the source-passage block, or an empty string when none."""
        if not context.chunks:
            return ""
        lines = ["Passages:"]
        for chunk in context.chunks:
            lines.append(f"[chunk:{chunk.id}] (source: {chunk.source})")
            lines.append(chunk.text)
            lines.append("")
        return "\n".join(lines).rstrip()
