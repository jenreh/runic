# Retrieval & answers

Once the graph is built, `runic.rag` answers questions by retrieving evidence
from it and synthesizing a cited answer. You call one method — `query()` — and
pick a *mode* that decides how widely the retriever fans out. Every answer comes
back as an `Answer` object carrying the synthesized text, the citations that
ground it, and the full retrieval context.

This page explains the three retrieval modes, how `hybrid` fuses several
strategies with Reciprocal Rank Fusion, the shape of the `Answer` object, and how
to pick a mode and tune it. For how the graph is populated in the first place,
see [ingestion](./ingestion.md); for the underlying ideas, see
[concepts](./concepts.md).

```python
from runic.rag import GraphRAG, RagSettings

rag = GraphRAG.with_defaults(settings=RagSettings())
answer = rag.query("Who founded Helios Energy?")
print(answer.text)
```

`query()` takes the question and an optional `mode` keyword:

```python
rag.query(q, *, mode="auto")  # mode in {"auto", "local", "hybrid"}
```

::: info
There are exactly three modes: `local`, `hybrid`, and `auto`. Any other value
raises `ValueError`. There is no global mode.
:::

---

## The three modes

Each mode selects a different set of retrievers. They trade precision and cost
against recall, in increasing breadth.

**`local`** runs a single neighbourhood walk. It embeds the query, seeds a KNN
vector search over the `Entity` index, then expands the entity neighbourhood up
to `max_hops` — pulling in neighbour entities, the relations traversed between
them, and the chunks for the whole set. It is precise and cheap (one embedding,
no extra LLM call), but recall is limited to whatever the nearest entities
happen to mention.

**`hybrid`** fans out across three complementary strategies and fuses them with
Reciprocal Rank Fusion (RRF):

- **vector** — semantic similarity over entity embeddings (finds related material).
- **fulltext** — exact lexical / keyword matches (finds the precise term a vector walk ranks lower).
- **highlevel** — an LLM extracts theme keywords from the question, then expands a thematic subgraph around the entities they match.

Because an item ranked highly by *any* of the three bubbles up in the fused
result, hybrid recovers lexical and thematic evidence a pure-vector walk misses —
higher recall, at the cost of one extra LLM call for the keyword step.

**`auto`** is the default. A light, dependency-free heuristic inspects the query
and routes it to `local` for short, entity-pointed questions or to `hybrid` for
broader, thematic ones — so you only pay for hybrid's breadth when the question
needs it. The rule is:

> A query is treated as **local** when it has **8 tokens or fewer AND contains no
> broad-cue word**. Otherwise it is treated as **hybrid**.

The broad-cue words (matched case-insensitively, with trailing `?`, `.`, or `,`
stripped) are:

```text
all, across, compare, overall, themes, trends,
summarize, summary, relationship, relationships, everything
```

So `"Who founded Helios Energy?"` (four tokens, no cue) routes to `local`, while
`"Compare the SOLARK-9000 with the overall storage market."` routes to `hybrid`
on the cue word `compare`.

| Mode | Retrievers | Best for | Cost |
| --- | --- | --- | --- |
| `local` | neighbourhood walk | focused, entity-pointed questions | cheapest |
| `hybrid` | vector + fulltext + highlevel, RRF-fused | broad, relational, thematic questions | +1 LLM call |
| `auto` | `local` or `hybrid` per the heuristic | mixed workloads (the default) | varies |

---

## How hybrid fuses results (RRF)

In `hybrid` mode each of the three retrievers returns its own ranked context.
The default `RRFReranker` fuses them with Reciprocal Rank Fusion: every item's
fused score is the sum of `1 / (k0 + rank + 1)` over each context it appears in,
where *rank* is its position in that context and `k0` is a constant (60 by
default). Entities are fused by `canonical_key`, chunks by `id`, and relations
are unioned by identity. The merged context is then sorted by descending fused
score and trimmed to `top_k`.

The practical effect: an item that any single retriever ranks highly rises in the
fused list, and an item that several retrievers agree on rises further. That is
how hybrid recovers a lexical match (a precise product code) or a thematic hit
(a topic keyword) that a vector-only walk would have ranked too low to surface.
RRF is deterministic and needs no model, which is why it is wired by default.

::: info
`CrossEncoderReranker` is an exported opt-in alternative that re-scores each
`(query, text)` pair with a sentence-transformers model. It is **not** wired by
`with_defaults` — see [configuration](./configuration.md) to swap it in. The RRF
idea is covered in [concepts](./concepts.md).
:::

---

## Running each mode

The clearest way to see the modes diverge is to run the same query through all
three and inspect the retrieved context. The fused `score` on each hit is exposed,
so you can watch RRF reorder and widen the results. Always guard `context` for
`None` before reading it.

```python
from runic.rag import GraphRAG, RagSettings

rag = GraphRAG.with_defaults(settings=RagSettings())

query = "Compare the SOLARK-9000 product with the overall energy storage market."

for mode in ("local", "hybrid", "auto"):
    answer = rag.query(query, mode=mode)
    context = answer.context
    if context is None:
        print(f"{mode}: (no retrieval context)")
        continue

    print(f"\n--- mode={mode!r} ---")
    for entity in context.entities:
        print(f"  entity: {entity.name} ({entity.type})  score={entity.score:.5f}")
    for chunk in context.chunks:
        snippet = chunk.text.replace("\n", " ").strip()[:72]
        print(f"  chunk:  [{chunk.source}] score={chunk.score:.5f}  {snippet}")
    print(f"  answer: {answer.text}")
```

For this broad query, `hybrid` typically surfaces at least as many entities and
chunks as `local`, and `auto` matches `hybrid` because the cue word `compare`
trips the heuristic. Swap in a short, entity-pointed query such as
`"Who founded Helios Energy?"` and `auto` instead matches `local`, staying cheap.

The full, runnable side-by-side comparison lives in
[`examples/rag/05_hybrid_retrieval.py`](https://github.com/jenreh/runic/blob/main/examples/rag/05_hybrid_retrieval.py).

---

## The Answer object

`query()` returns a frozen `Answer`:

```python
answer = rag.query("How is Ada Lovelace connected to the Analytical Engine?")

print(answer.text)              # str — the synthesized, grounded answer
for citation in answer.citations:
    print(citation.source, citation.chunk_id)
    print(citation.text)        # the exact source chunk text backing the answer

context = answer.context        # RetrievalContext | None
```

`Answer` has three fields:

- `text: str` — the synthesized answer.
- `citations: list[Citation]` — the source chunks that support the answer. Each
  `Citation` carries `chunk_id`, `source`, and `text`.
- `context: RetrievalContext | None` — the evidence retrieval assembled. May be
  `None`, so guard it.

The `RetrievalContext` holds the fused evidence behind the answer:

- `entities: list[EntityHit]` — each with `canonical_key`, `name`, `type`,
  `description`, and `score`.
- `chunks: list[ChunkHit]` — each with `id`, `text`, `source`, and `score`.
- `relations: list[RelationHit]` — each with `source_key`, `target_key`,
  `rel_type`, and `description`.

### Grounding with citations

Use `citations` to verify or display *where* an answer came from. Each citation
points at a real source chunk, so you can show provenance to the user or check
that a claim is backed by ingested text rather than invented. Because chunks keep
their `source` tag through ingestion, citations for a cross-document answer span
multiple sources:

```python
answer = rag.query(
    "How is Ada Lovelace connected to the Analytical Engine and Alan Turing?",
    mode="hybrid",
)
print(answer.text)

sources_seen: set[str] = set()
for citation in answer.citations:
    sources_seen.add(citation.source)
    snippet = citation.text.replace("\n", " ").strip()[:80]
    print(f"  - [{citation.source}] {snippet}")
print(f"distinct sources cited: {len(sources_seen)}")
```

You can also walk `context.relations` to show how the entities are linked in the
graph:

```python
context = answer.context
if context is not None:
    for relation in context.relations:
        print(f"{relation.source_key} -[{relation.rel_type}]-> {relation.target_key}")
```

::: info
Full field tables for `Answer`, `Citation`, `RetrievalContext`, `EntityHit`,
`ChunkHit`, and `RelationHit` live in the [API reference](./api.md).
:::

---

## Choosing a mode and tuning

Pick the mode to match the question:

- **Short, entity-pointed questions** ("Who founded X?", "When was Y released?")
  → `local`. The answer lives in one entity's neighbourhood, so the cheap walk is
  enough.
- **Broad, relational, or thematic questions** ("Compare A and B", "What are the
  trends across these documents?") → `hybrid`. You need recall across the whole
  graph, and the fulltext + theme strategies pull in evidence a vector walk
  misses.
- **Mixed workloads** → leave it on `auto` and let the heuristic decide
  per-query. Reach for an explicit mode only when you want to force the cheaper or
  the broader path.

Two knobs shape every result, both read from settings:

| Variable | Meaning | Default |
| --- | --- | --- |
| `top_k` | How many items each retriever returns and how many survive the fuse. Higher widens recall but admits weaker hits, lowering precision. | `10` |
| `max_hops` | How far `local` and the thematic walk expand the entity neighbourhood. Higher reaches more related entities and relations (more recall) but pulls in more loosely-connected noise. | `2` |

Raising `top_k` broadens what reaches synthesis; raising `max_hops` deepens the
neighbourhood each seed explores. Both trade recall for precision, so tune them
against your own questions rather than guessing. Defer the actual defaults and how
to override them to [configuration](./configuration.md), and measure the trade-off
empirically with [evaluation](./evaluation.md).

---

## Next steps

::: info See also
- [Ingesting documents](./ingestion.md) — how the graph retrieval reads from is built.
- [Designing & optimizing ontologies](./ontologies.md) — shape the entity vocabulary so retrieval has the right targets.
- [Evaluating quality](./evaluation.md) — measure faithfulness, recall, and precision to tune `top_k` / `max_hops`.
- [Configuration & deployment](./configuration.md) — set retrieval knobs, swap the reranker, and choose a backend.
- [API Reference](./api.md) — full field tables for `Answer`, `Citation`, and `RetrievalContext`.
- [`examples/rag/05_hybrid_retrieval.py`](https://github.com/jenreh/runic/blob/main/examples/rag/05_hybrid_retrieval.py) — the runnable local vs hybrid vs auto comparison.
:::
