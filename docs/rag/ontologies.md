# Designing & optimizing ontologies

An ontology is the set of *hard entity types* the extractor is told to find, paired with their backing OGM models. When `runic.rag` reads a document, it hands the extractor `ontology.entity_types()` as the allowed vocabulary and asks it to classify every entity into one of those buckets. Choosing that vocabulary well is the single highest-leverage quality knob in Graph-RAG — it costs nothing extra at ingest time and shapes every answer that follows.

This page shows the three ways to build an `Ontology`, explains *why* better types produce better answers, and teaches an A/B methodology for tuning a vocabulary against a real corpus.

---

## Why types matter

The extractor does not invent its own taxonomy. It classifies each entity into one of the names you supply, so the vocabulary is a constraint, not a suggestion. A tuned, domain-specific vocabulary pays off three ways:

- **It removes ambiguity.** A "framework" tagged `Technology` is unambiguous; the generic ontology would force it into the vague `Concept` or `Product`. Sharper labels mean fewer near-duplicate, miscategorised nodes.
- **It suppresses noise.** Types absent from the list are not invited, so the model stops minting off-topic categories. The graph stays focused on the concepts you actually query.
- **It yields cleaner neighbourhoods.** Downstream `type` filters and graph expansion line up with the buckets you care about. Local-mode walks land on relevant nodes, and type-filtered retrieval returns sharper context — so the synthesizer sees less off-topic text and the answer is more grounded.

In short: better types produce cleaner neighbourhoods, and cleaner neighbourhoods produce sharper answers. The ontology you pick also feeds the hybrid ontology the graph is built on — see [concepts](./concepts.md) for how entities, chunks, and relations fit together, and [retrieval](./retrieval.md) for how typed neighbourhoods are walked at query time.

---

## Three ways to build an Ontology

The ontology drives **both** `bootstrap_schema()` (it creates the subtype labels and their indexes) and extraction (it constrains the allowed types). Pick the construction style that matches how much control you need.

### 1. The built-in default

`Ontology.default()` ships a generic, batteries-included vocabulary: `Person`, `Organization`, `Location`, `Concept`, `Product`, `Event`. It is what `GraphRAG.with_defaults(...)` uses when you pass no `ontology=`. Good for a first pass or a mixed corpus with no strong domain.

```python
from runic.rag import GraphRAG, Ontology, RagSettings

ontology = Ontology.default()
print(ontology.entity_types())
# ['Person', 'Organization', 'Location', 'Concept', 'Product', 'Event']

rag = GraphRAG.with_defaults(settings=RagSettings(), ontology=ontology)
```

### 2. From a list of type names

`Ontology.from_types([...])` is the fastest way to iterate on a domain vocabulary — no class boilerplate. It reuses the built-in subtypes when a name matches (`Person`, `Concept`, ...) and dynamically mints a fresh `Entity` subclass for the rest:

```python
from runic.rag import GraphRAG, Ontology, RagSettings

ontology = Ontology.from_types(["Person", "Project", "Technology", "Concept"])
print(ontology.entity_types())
# ['Person', 'Project', 'Technology', 'Concept']

rag = GraphRAG.with_defaults(settings=RagSettings(), ontology=ontology)
rag.bootstrap_schema()
```

This is the recommended starting point for tuning: change the list, re-ingest, compare.

### 3. Custom Entity subclasses

When you need extra fields or indexes on a subtype, declare explicit `Entity` subclasses and pass them to `Ontology(entity_models=[...])`. The class keywords route through the OGM `Node` metaclass — `labels=["Entity", T]` keeps every subtype under the shared `Entity` label (so the base schema and indexes still apply), and `primary_label="Entity"` keeps a single primary key:

```python
from runic.rag import Entity, GraphRAG, Ontology, RagSettings


class Person(Entity, labels=["Entity", "Person"], primary_label="Entity"):
    """A person, e.g. a creator or contributor."""


class Project(Entity, labels=["Entity", "Project"], primary_label="Entity"):
    """A software project, library, or framework."""


class Technology(Entity, labels=["Entity", "Technology"], primary_label="Entity"):
    """A language, runtime, or platform."""


class Concept(Entity, labels=["Entity", "Concept"], primary_label="Entity"):
    """A pattern, methodology, or abstract idea."""


ontology = Ontology(entity_models=[Person, Project, Technology, Concept])
rag = GraphRAG.with_defaults(settings=RagSettings(), ontology=ontology)
rag.bootstrap_schema()
```

The base `Entity` already carries `canonical_key` (primary key), `name` and `description` (fulltext-indexed), an indexed `type` string, and an `embedding` vector. Subclassing adds your own `Field()`s on top of that shared schema.

::: info
The exact subclass signature — `class Project(Entity, labels=["Entity", "Project"], primary_label="Entity")` — matters. The non-`Entity` label is the subtype name the extractor classifies into, and keeping `primary_label="Entity"` is what lets every subtype share one identity and one set of base indexes. `Ontology.from_types([...])` mints exactly this shape for you.
:::

Both `from_types` and `entity_models` are illustrated side by side in [`examples/rag/02_custom_ontology.py`](https://github.com/jenreh/runic/blob/main/examples/rag/02_custom_ontology.py) — the two builders there yield an equivalent vocabulary, so pick whichever fits.

---

## The A/B methodology

Tuning is empirical: you cannot tell from the type names alone whether a vocabulary fits a corpus. The reliable approach is an A/B run — ingest the **same text** into two graphs under two ontologies, with the **same budget** and the **same question**, then compare. This is exactly what [`examples/rag/04_manager_magazin_pdf.py`](https://github.com/jenreh/runic/blob/main/examples/rag/04_manager_magazin_pdf.py) does with a real business-magazine PDF.

The setup uses two distinct graphs so the ontologies never share state — `mm_default` built with `Ontology.default()`, and `mm_tuned` built with a hand-tuned business/finance vocabulary:

```python
from runic.rag import Ontology

TUNED_TYPES = [
    "Company",
    "Executive",
    "Industry",
    "FinancialMetric",
    "Product",
    "Market",
    "Person",
    "Location",
]

default_ontology = Ontology.default()
tuned_ontology = Ontology.from_types(TUNED_TYPES)
```

### Measure typed coverage

The headline metric is **typed coverage**: the fraction of entities whose `type` falls inside the ontology vocabulary. Higher means more entities landed in meaningful, queryable buckets instead of a catch-all (or no type at all):

```python
def typed_coverage(counts: dict[str, int], vocabulary: list[str]) -> float:
    """Fraction of entities whose type is a recognised ontology type [0, 1]."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    vocab = set(vocabulary)
    typed = sum(n for label, n in counts.items() if label in vocab)
    return typed / total
```

### Build the entity-type histogram

The per-type counts come straight from the graph. Query `Entity` nodes grouped by their `type` property through the driver and read `result.rows`:

```python
def entity_counts_by_type(driver) -> dict[str, int]:
    """Return a histogram of Entity nodes grouped by their `type` property."""
    result = driver.execute(
        "MATCH (e:Entity) RETURN coalesce(e.type, '') AS t, count(*) AS c", {}
    )
    counts: dict[str, int] = {}
    for row in result.rows:
        label = str(row[0]) if row[0] else "(untyped)"
        counts[label] = counts.get(label, 0) + int(row[1])
    return counts
```

Feed each graph's histogram to `typed_coverage(...)` with the matching vocabulary and print the two side by side:

```python
default_cov = typed_coverage(
    entity_counts_by_type(default_driver), Ontology.default().entity_types()
)
tuned_cov = typed_coverage(
    entity_counts_by_type(tuned_driver), TUNED_TYPES
)
print(f"generic typed coverage: {default_cov:.1%}")
print(f"tuned   typed coverage: {tuned_cov:.1%}")
```

### Read the result

Run against the same slice and the contrast is stark. The generic ontology dumps most nodes into `Organization`/`Concept`; the tuned ontology splits them into `Company` / `Executive` / `Industry` / `FinancialMetric` / `Market` — buckets you can actually query and filter. Both graphs answer the same finance question, but the tuned graph's neighbourhoods are sharper, so its answer is more grounded.

The takeaway from the flagship example is blunt: same text, same budget, same question — only the ontology changed. Tuning the vocabulary is the cheapest, highest-leverage quality win in Graph-RAG. No model change, no extra gleaning passes, just better types. The same `typed_coverage` and histogram helpers double as a quality signal in your eval harness — see [evaluation](./evaluation.md).

---

## An optimization checklist

::: tip Tuning an ontology
- **Name types after the questions you actually ask.** If users ask "which companies and executives", make `Company` and `Executive` first-class types — do not rely on a generic `Organization` to cover both.
- **Keep it to 5–12 types.** Too few collapses distinct concepts into one bucket; too many overwhelms the extractor and re-creates the ambiguity you were trying to remove.
- **Avoid overlapping or ambiguous types.** If `Company` and `Organization` would both apply to the same node, drop one. Every entity should have one obvious home.
- **Prefer `from_types` for quick iteration.** Change the list, re-ingest, re-measure. Reach for custom subclasses only when you genuinely need extra fields or indexes.
- **Iterate against an eval set.** Use typed coverage and answer quality as your fitness function, and lock the gains in with a repeatable eval suite rather than eyeballing one answer.
:::

---

## Next steps

::: info See also
- [retrieval](./retrieval.md) — how typed neighbourhoods are walked and fused into answer context
- [evaluation](./evaluation.md) — turn the A/B comparison into a repeatable quality gate
- [api](./api.md) — the full `Ontology` surface (`default`, `from_types`, `entity_types`, `subtype_for`, `schema_models`)
- [`examples/rag/02_custom_ontology.py`](https://github.com/jenreh/runic/blob/main/examples/rag/02_custom_ontology.py) — `from_types` and custom subclasses side by side
- [`examples/rag/04_manager_magazin_pdf.py`](https://github.com/jenreh/runic/blob/main/examples/rag/04_manager_magazin_pdf.py) — the full A/B tuning run on a real PDF
:::
