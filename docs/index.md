---
layout: home

title: runic — Python Graph OGM, Graph-RAG & Schema Migrations
titleTemplate: false
description: runic is a Python graph OGM, Graph-RAG toolkit and schema-migration engine for Cypher graph databases — FalkorDB, Neo4j, Memgraph, ArcadeDB, Apache AGE and Amazon Neptune.

head:
  - - meta
    - name: keywords
      content: runic, python graph ogm, graph ogm, graph rag, graph rag python, python graph database, python graphdb, cypher ogm, falkordb python, neo4j python ogm, memgraph python, apache age python, graph schema migrations, knowledge graph python
  - - script
    - type: application/ld+json
    - |-
      {
        "@context": "https://schema.org",
        "@graph": [
          {
            "@type": "SoftwareApplication",
            "@id": "https://runic.rehpoehler.de/#software",
            "name": "runic",
            "alternateName": ["runic-py", "runic.ogm", "runic.rag"],
            "applicationCategory": "DeveloperApplication",
            "applicationSubCategory": "Object-Graph Mapper (OGM) and Graph-RAG library",
            "description": "runic is a Python graph OGM, Graph-RAG toolkit and Alembic-style schema-migration engine for Cypher graph databases. One typed model definition runs on FalkorDB, Neo4j, Memgraph, ArcadeDB, Apache AGE and Amazon Neptune.",
            "url": "https://runic.rehpoehler.de/",
            "downloadUrl": "https://pypi.org/project/runic-py/",
            "codeRepository": "https://github.com/jenreh/runic",
            "programmingLanguage": "Python",
            "runtimePlatform": "Python 3.14",
            "operatingSystem": "Linux, macOS, Windows",
            "license": "https://opensource.org/licenses/MIT",
            "author": { "@type": "Person", "name": "Jens Rehpöhler" },
            "offers": { "@type": "Offer", "price": "0", "priceCurrency": "EUR" },
            "keywords": "graph OGM, Graph-RAG, Python graph database, Cypher, knowledge graph, schema migrations"
          },
          {
            "@type": "FAQPage",
            "@id": "https://runic.rehpoehler.de/#faq",
            "mainEntity": [
              {
                "@type": "Question",
                "name": "What is a graph OGM?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "A graph OGM (object-graph mapper) is to graph databases what an ORM is to relational ones. Instead of writing Cypher and reading back raw rows, you declare typed Python classes; the OGM maps them to nodes, edges, labels and relationship types, tracks changes, and generates the queries. In runic you subclass Node and Edge, declare Field and Relation attributes, and a Session handles reads, writes and change tracking."
                }
              },
              {
                "@type": "Question",
                "name": "Which graph databases does runic support?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "runic supports FalkorDB, Neo4j, Memgraph, ArcadeDB, Apache AGE (the PostgreSQL graph extension) and Amazon Neptune (Database and Analytics). The same model and query code runs on all seven — switching backend means changing the arguments to create_driver(), not rewriting your models."
                }
              },
              {
                "@type": "Question",
                "name": "Does runic support async Python?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "Yes. AsyncSession and AsyncRepository mirror the synchronous API call for call, so async code is the same code awaited. There are no hidden lazy loads, so query patterns stay deterministic under concurrency."
                }
              },
              {
                "@type": "Question",
                "name": "What is Graph-RAG, and how does runic implement it?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "Graph-RAG grounds LLM answers in a knowledge graph instead of a flat vector index, so retrieval can follow relationships between entities rather than only matching similar text. runic.rag ingests documents by chunking them, extracting entities and relations against an ontology, embedding them and storing everything as a graph. Retrieval fuses graph traversal and vector search with reciprocal rank fusion, and every answer comes back with citations to its source chunks."
                }
              },
              {
                "@type": "Question",
                "name": "Can I still write raw Cypher with runic?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "Yes. The query builder covers traversals, filtering, aggregation, paging, vector KNN and fulltext search, and every builder call prints the Cypher it compiles to. When you need something the builder does not model, you can run a raw Cypher statement through the same session and driver."
                }
              },
              {
                "@type": "Question",
                "name": "Do I need Docker to test code written with runic?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "No. runic's test guide uses an embedded, in-process FalkorDB, so unit tests covering CRUD, relationships and queries run without any external server or container. Docker is only needed when you want to test against a specific live backend."
                }
              },
              {
                "@type": "Question",
                "name": "Which Python version does runic require, and is it open source?",
                "acceptedAnswer": {
                  "@type": "Answer",
                  "text": "runic requires Python 3.14 or newer and is published on PyPI as runic-py. It is open source under the MIT license, developed at github.com/jenreh/runic."
                }
              }
            ]
          }
        ]
      }

hero:
  name: "runic"
  text: "Python graph OGM & Graph-RAG"
  tagline: Map Python classes to graph nodes and edges, version your schema like Alembic, and ground LLM answers in a knowledge graph — on FalkorDB, ArcadeDB, Neo4j, Memgraph, Apache AGE or Amazon Neptune.
  image:
    src: /runic.svg
    alt: runic — Python graph OGM for Cypher graph databases
  actions:
    - theme: brand
      text: Get Started
      link: /installation
    - theme: alt
      text: OGM Quickstart
      link: /ogm/quickstart
    - theme: alt
      text: Migration Quickstart
      link: /migration/quickstart
    - theme: alt
      text: Graph-RAG Quickstart
      link: /rag/quickstart

features:
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-waypoints-icon lucide-waypoints"><circle cx="12" cy="4.5" r="2.5"/><path d="m10.2 6.3-3.9 3.9"/><circle cx="4.5" cy="12" r="2.5"/><path d="M7 12h10"/><circle cx="19.5" cy="12" r="2.5"/><path d="m13.8 17.7 3.9-3.9"/><circle cx="12" cy="19.5" r="2.5"/></svg>'
    title: Python graph OGM
    details: Map Python classes to graph nodes and edges. Typed fields, indexes, constraints, lazy/eager relationships, and a fluent query builder that compiles to Cypher.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-refresh-cw-icon lucide-refresh-cw"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M3 21v-5h5"/></svg>'
    title: Graph schema migrations
    details: Alembic-style versioned migration engine for graph databases. Track index and constraint changes as replayable scripts with upgrade and downgrade paths.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-plug-icon lucide-plug"><path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/></svg>'
    title: Five graph databases, one model
    details: A pluggable driver layer supports FalkorDB, ArcadeDB, Neo4j, Memgraph, Apache AGE (PostgreSQL), and Amazon Neptune. Switch graph database without rewriting your models.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-zap-icon lucide-zap"><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>'
    title: Async-first Python API
    details: AsyncSession mirrors the sync API call for call. No hidden lazy loads — deterministic query patterns for high-throughput Python applications.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-test-tube-diagonal-icon lucide-test-tube-diagonal"><path d="M21 7 6.82 21.18a2.83 2.83 0 0 1-3.99-.01 2.83 2.83 0 0 1 0-4L17 3"/><path d="m16 2 6 6"/><path d="M12 16H4"/></svg>'
    title: Test without Docker
    details: Run unit tests against an embedded, in-process FalkorDB. No container required — full CRUD, relationship, and query coverage in your test suite.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-search-icon lucide-search"><path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/></svg>'
    title: Vector & fulltext search
    details: Native vector KNN and fulltext search on your graph. Declare vector indexes in your model, query with vector_search() — no raw Cypher needed.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-network-icon lucide-network"><rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/></svg>'
    title: Graph-RAG for Python
    details: Turn documents into a knowledge graph, then answer questions over it with citations. Pluggable chunking, extraction, embedding, and retrieval — OpenAI by default or fully local via Ollama.
---

## What is runic?

**runic is a Python graph OGM — an object-graph mapper for Cypher graph
databases.** You declare typed `Node` and `Edge` classes, and runic maps them
to labels, relationship types, indexes and constraints, tracks your changes,
and compiles a fluent query API down to Cypher. The same model code runs
unchanged on **FalkorDB, ArcadeDB, Neo4j, Memgraph, Apache AGE and Amazon Neptune**
(the PostgreSQL graph extension).

Two more layers ship in the same Python package:

- **Graph schema migrations** — an Alembic-style migration engine for graph
  databases, with versioned revision scripts, a CLI, and rollback.
- **Graph-RAG** — a Graph-RAG SDK that turns documents into a knowledge graph
  and answers questions over it with citations back to the source text.

```bash
uv add "runic-py[falkordb]"     # or: pip install "runic-py[falkordb]"
```

runic requires Python 3.14+, is MIT-licensed, and is published on PyPI as
[`runic-py`](https://pypi.org/project/runic-py/).

## Graph OGM — map Python classes to nodes and edges

Map classes to nodes, write a relationship, then traverse it with the
fluent query builder — no raw Cypher:

```python
from runic.ogm import (
    Field,
    Node,
    Relation,
    Session,
    alias,
    create_driver,
    select,
)

class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True)
    name: str
    email: str = Field(unique=True)
    friends: list["Person"] = Relation(
        relationship="FRIENDS",
        direction="OUTGOING",
        target="Person",
    )

driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")

with Session(driver) as session:
    alice = Person(id="alice", name="Alice", email="alice@example.com")
    bob = Person(id="bob", name="Bob", email="bob@example.com")
    session.add(alice)
    session.add(bob)
    session.relate(alice, Person.friends, bob)
    session.commit()

    # Traverse the social graph: everyone Alice is friends with
    p, f = alias(Person, "p"), alias(Person, "f")
    stmt = (
        select(p)
        .where(p.id == "alice")
        .traverse(Person.friends, to=f)
        .return_target(f)
    )
    friends: list[Person] = session.scalars(stmt)
    print([person.name for person in friends])   # ['Bob']
    # MATCH (p:Person)
    # WHERE p.id = $p0
    # MATCH (p)-[:FRIENDS]->(f:Person)
    # RETURN f
```

## Graph schema migrations — versioned, replayable, reversible

Track graph schema changes as versioned revision scripts, the way Alembic
does for SQL. Generate one with `runic revision`, then describe the change
with `op.*` calls:

```python
# runic/versions/3f9a12c1_add_person_email_index.py

def upgrade(op) -> None:
    op.create_range_index("Person", "email")

def downgrade(op) -> None:
    op.drop_range_index("Person", "email")
```

Apply and roll back from the CLI:

```bash
runic revision -m "add person email index"   # scaffold the script above
runic upgrade                                 # apply pending revisions
runic current                                 # 3f9a12c1 — add person email index
runic downgrade base                          # roll back to an empty schema
```

## Graph-RAG in Python — knowledge graphs with cited answers

Turn unstructured text into a knowledge graph, then ask questions and get
answers grounded in cited source chunks — extraction, embedding, storage, and
hybrid retrieval handled for you:

```bash
uv add "runic-py[graphrag,falkordb]"   # Graph-RAG extras + a backend driver
```

```python
from runic.ogm import create_driver
from runic.rag import GraphRAG, Ontology, RagSettings

settings = RagSettings()
driver = create_driver(
    "falkordb", host="localhost", port=6379, graph=settings.falkordb_graph
)

rag = GraphRAG.with_defaults(driver, settings=settings, ontology=Ontology.default())
rag.bootstrap_schema()
rag.ingest_text(
    "Ada Lovelace worked with Charles Babbage on the Analytical Engine.",
    source="inline-demo",
)

answer = rag.query("Who worked on the Analytical Engine?")
print(answer.text)
for citation in answer.citations:
    print(f"  - [{citation.source}] {citation.text[:80]}...")
```

Set `OPENAI_API_KEY` first (or point runic.rag at Ollama for a fully local
run). `mode="auto"` picks a focused or broad retrieval strategy per question.

## Supported graph databases

One model definition, seven backends. Switching graph database means changing
the arguments to `create_driver()` — your models, queries, and application
code stay the same.

| Graph database | Install extra | Notes |
| --- | --- | --- |
| [FalkorDB](/ogm/drivers) | `runic-py[falkordb]` | Redis-based; also runs embedded and in-process for tests |
| [Neo4j](/ogm/drivers) | `runic-py[neo4j]` | Official Bolt driver |
| [Memgraph](/ogm/drivers) | `runic-py[memgraph]` | In-memory, over Bolt |
| [ArcadeDB](/ogm/drivers) | `runic-py[arcadedb]` | Multi-model, over Bolt |
| [Apache AGE](/ogm/drivers) | `runic-py[age]` | Graphs inside PostgreSQL |
| [Amazon Neptune Database](/ogm/drivers) | `runic-py[neptune]` | AWS-managed, over Bolt with IAM auth |
| [Amazon Neptune Analytics](/ogm/drivers) | `runic-py[neptune-analytics]` | AWS-managed, HTTPS, native vector search |

See [Supported Drivers](/ogm/drivers) for connection options and per-backend
capability differences.

## Beyond the basics

These snippets barely scratch it. runic is built for the hard parts of
real graph work — the things you hit on day two, not day one:

- **Multi-hop and variable-length traversals** — chain `.traverse()` calls
  or use `.traverse(..., hops=(min, max))` to walk org charts, dependency
  trees, and recommendation paths without hand-writing `*1..5` Cypher.
- **Edge properties as first-class data** — model the relationship itself
  with `Edge`, read it back with `all_with_edges()`, and filter on the edge.
- **Lazy vs. eager loading, on your terms** — no hidden N+1 surprises;
  you decide what gets fetched and when.
- **Vector KNN and fulltext search** — declare the index on your model and
  query it with `vector_search()` / `fulltext_search()` — native, not bolted on.
- **Async that mirrors the sync API** — the same calls, `await`-ed.
- **Migrations that travel** — the same `upgrade`/`downgrade` workflow runs
  unchanged across FalkorDB, ArcadeDB, Neo4j, Memgraph, Apache AGE, and Amazon Neptune.

## Frequently asked questions

### What is a graph OGM?

A graph OGM (object-graph mapper) is to graph databases what an ORM is to
relational ones. Instead of writing Cypher and reading back raw rows, you
declare typed Python classes; the OGM maps them to nodes, edges, labels and
relationship types, tracks changes, and generates the queries. In runic you
[define models](/ogm/concepts) by subclassing `Node` and `Edge` and declaring
`Field` and `Relation` attributes, and a [`Session`](/ogm/session) handles
reads, writes and change tracking.

### Which graph databases does runic support?

FalkorDB, Neo4j, Memgraph, ArcadeDB, Apache AGE (the PostgreSQL graph
extension) and Amazon Neptune — Database and Analytics. The same model and
query code runs on all seven — see
[Supported Drivers](/ogm/drivers).

### Does runic support async Python?

Yes. `AsyncSession` and `AsyncRepository` mirror the synchronous API call for
call, so async code is the same code awaited. There are no hidden lazy loads,
so query patterns stay deterministic under concurrency. See the
[Async Guide](/ogm/async).

### What is Graph-RAG, and how does runic implement it?

Graph-RAG grounds LLM answers in a knowledge graph instead of a flat vector
index, so retrieval can follow relationships between entities rather than only
matching similar text. `runic.rag` ingests documents by chunking them,
extracting entities and relations against an
[ontology](/rag/ontologies), embedding them, and storing everything as a
graph. [Retrieval](/rag/retrieval) fuses graph traversal and vector search with
reciprocal rank fusion, and every answer comes back with citations to its
source chunks. Start with [What is Graph-RAG?](/rag/concepts).

### Can I still write raw Cypher with runic?

Yes. The [query builder](/ogm/query-builder) covers traversals, filtering,
aggregation, paging, vector KNN and fulltext search, and every builder call
documents the Cypher it compiles to. When you need something the builder does
not model, run a raw Cypher statement through the same session and driver.

### Do I need Docker to test code written with runic?

No. The [testing guide](/ogm/testing) uses an embedded, in-process FalkorDB, so
unit tests covering CRUD, relationships and queries run without any external
server or container. Docker is only needed when you want to test against a
specific live backend.

### Which Python version does runic require, and is it open source?

runic requires Python 3.14 or newer and is published on PyPI as
[`runic-py`](https://pypi.org/project/runic-py/). It is open source under the
MIT license, developed at [github.com/jenreh/runic](https://github.com/jenreh/runic).

## Where to go next

Start with a quickstart and you'll have something running in five minutes:

- [OGM Quickstart](/ogm/quickstart) — model, query, and persist your first graph
- [Migration Quickstart](/migration/quickstart) — version your schema from zero
- [Graph-RAG Quickstart](/rag/quickstart) — turn documents into a cited, queryable knowledge graph

Then go deep:

- [Relationships](/ogm/relationships) — lazy/eager loading, `relate()`, edge properties
- [Query Builder](/ogm/query-builder) — traversals, aggregation, the Cypher behind every call
- [Async](/ogm/async) — the full async surface
- [Operations Reference](/migration/operations-reference) — every `op.*` call at a glance
- [Designing & optimizing ontologies](/rag/ontologies) — the highest-leverage knob for Graph-RAG quality

> Bring your own backend. Write your models once. runic handles the Cypher.
