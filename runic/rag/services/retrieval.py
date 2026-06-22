"""Query-side orchestration for runic.rag (CQRS-light read model).

:class:`RetrievalService` answers a natural-language query end to end:

1. pick a *retrieval mode* (``local``, ``hybrid``, or ``auto``),
2. run the retriever(s) that mode selects,
3. fuse / rerank their contexts into a single
   :class:`~runic.rag.domain.RetrievalContext`, and
4. hand that context to the :class:`~runic.rag.ports.Synthesizer` for a cited
   :class:`~runic.rag.domain.Answer`.

Mode selection is **dict dispatch** (``_MODES``) rather than an ``if/elif``
ladder, so new modes are added open/closed (ADR-017) by registering a planner
function — no edits to :meth:`RetrievalService.query`.

Every collaborator is a port injected via the constructor (DIP); the service
itself never touches a backend or the network, which makes it trivially
unit-testable with the fakes in ``tests/runic/rag/fakes.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from runic.rag.domain import RetrievalContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from runic.rag.config import RagSettings
    from runic.rag.domain import Answer
    from runic.rag.ports import Embedder, GraphStore, Reranker, Retriever, Synthesizer

log = logging.getLogger(__name__)

__all__ = [
    "RetrievalService",
]

# Canonical retriever names this service knows how to plan around. Adapters are
# registered under these keys; a missing key simply drops that strategy.
_LOCAL = "local"
_VECTOR = "vector"
_FULLTEXT = "fulltext"
_HIGHLEVEL = "highlevel"

# Hybrid breadth: every strategy whose context feeds the RRF fusion step.
_HYBRID_RETRIEVERS: tuple[str, ...] = (_VECTOR, _FULLTEXT, _HIGHLEVEL)

# A planner maps the service + query to the ordered retriever names to run.
_Planner = Callable[["RetrievalService", str], list[str]]


class RetrievalService:
    """Compose retrievers, a reranker, and a synthesizer into a query pipeline.

    Args:
        store: The graph store port (held for future direct lookups / parity
            with the ingestion service; the injected retrievers own all reads).
        retrievers: A mapping of retriever name → :class:`Retriever`. Expected
            keys are ``"local"``, ``"vector"``, ``"fulltext"``, ``"highlevel"``;
            absent keys are skipped, so a partial wiring still works.
        reranker: Fuses multiple contexts into one (RRF by default).
        synthesizer: Turns the fused context into a cited :class:`Answer`.
        embedder: The embedder port (held for parity / future query embedding;
            the retrievers embed internally).
        settings: Runtime configuration (``top_k`` drives retrieval breadth).
    """

    def __init__(
        self,
        *,
        store: GraphStore,
        retrievers: Mapping[str, Retriever],
        reranker: Reranker,
        synthesizer: Synthesizer,
        embedder: Embedder,
        settings: RagSettings,
    ) -> None:
        self._store = store
        self._retrievers = dict(retrievers)
        self._reranker = reranker
        self._synthesizer = synthesizer
        self._embedder = embedder
        self._settings = settings

    def query(self, q: str, *, mode: str = "auto") -> Answer:
        """Answer *q*, selecting the retriever set by *mode* (dict dispatch).

        ``mode`` must be one of :data:`_MODES`. The chosen planner returns the
        ordered retriever names to run; their contexts are reranked/fused and
        synthesized into a cited :class:`Answer`.
        """
        planner = self._MODES.get(mode)
        if planner is None:
            valid = ", ".join(sorted(self._MODES))
            raise ValueError(
                f"Unknown retrieval mode {mode!r}; expected one of {valid}"
            )

        names = planner(self, q)
        contexts = self._run_retrievers(q, names)
        fused = self._fuse(q, contexts)
        log.debug(
            "query mode=%s ran %d retriever(s) -> %d entities, %d chunks",
            mode,
            len(contexts),
            len(fused.entities),
            len(fused.chunks),
        )
        return self._synthesizer.synthesize(q, fused)

    # ── Planners (registered in _MODES) ──────────────────────────────────────

    def _plan_local(self, q: str) -> list[str]:  # noqa: ARG002 - signature parity
        """Local mode: the neighbourhood-expanding retriever only."""
        return [_LOCAL]

    def _plan_hybrid(self, q: str) -> list[str]:  # noqa: ARG002 - signature parity
        """Hybrid mode: every available breadth strategy, fused by the reranker."""
        return list(_HYBRID_RETRIEVERS)

    def _plan_auto(self, q: str) -> list[str]:
        """Auto mode: a light classifier picks local vs hybrid for *q*.

        Short, entity-pointed questions favour the cheaper local neighbourhood
        walk; broader/thematic questions fan out across the hybrid strategies.
        """
        if self._is_local_query(q):
            return self._plan_local(q)
        return self._plan_hybrid(q)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_local_query(q: str) -> bool:
        """Heuristic query classifier: True ⇒ a focused, local-style question.

        Cheap and dependency-free: a question is "local" when it is short
        (few tokens) and lacks the broad/thematic cue words that signal a
        cross-cutting query better served by the hybrid fan-out.
        """
        tokens = q.split()
        broad_cues = {
            "all",
            "across",
            "compare",
            "overall",
            "themes",
            "trends",
            "summarize",
            "summary",
            "relationship",
            "relationships",
            "everything",
        }
        lowered = {token.strip("?.,").lower() for token in tokens}
        if lowered & broad_cues:
            return False
        return len(tokens) <= 8

    def _run_retrievers(self, q: str, names: list[str]) -> list[RetrievalContext]:
        """Run each named retriever that is wired, preserving order."""
        top_k = self._settings.top_k
        contexts: list[RetrievalContext] = []
        for name in names:
            retriever = self._retrievers.get(name)
            if retriever is None:
                log.debug("retriever %r not wired; skipping", name)
                continue
            contexts.append(retriever.retrieve(q, top_k=top_k))
        return contexts

    def _fuse(self, q: str, contexts: list[RetrievalContext]) -> RetrievalContext:
        """Collapse *contexts* into one reranked context for synthesis."""
        if not contexts:
            return RetrievalContext(query=q)
        return self._reranker.rerank(q, contexts, top_k=self._settings.top_k)

    # Dict dispatch table (ADR-017 / OCP): mode name → planner. Registering a
    # new mode here is the only change needed to support it; `query` stays
    # closed against modification.
    _MODES: dict[str, _Planner] = {
        _LOCAL: _plan_local,
        "hybrid": _plan_hybrid,
        "auto": _plan_auto,
    }
