---
layout: home

hero:
  name: "runic"
  text: "Graph schema migrations and OGM"
  tagline: For Cypher-based graph databases — FalkorDB, ArcadeDB, Neo4j, Memgraph, Apache AGE.
  image:
    src: /runic.svg
    alt: runic
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

features:
  - icon: 🗂️
    title: Graph OGM
    details: Map Python classes to nodes and edges. Typed fields, indexes, constraints, lazy/eager relationships, and a fluent query builder.
  - icon: 🔄
    title: Schema migrations
    details: Alembic-style versioned migration engine. Track index and constraint changes as replayable scripts with upgrade and downgrade paths.
  - icon: 🔌
    title: Multi-backend
    details: Pluggable driver layer supports FalkorDB, ArcadeDB, Neo4j, Memgraph, and Apache AGE (PostgreSQL). Switch backends without rewriting models.
  - icon: ⚡
    title: Async first-class
    details: AsyncSession mirrors the sync API. No hidden lazy loads — deterministic query patterns for high-throughput applications.
  - icon: 🧪
    title: Testable by design
    details: Embedded FalkorDB via redislite. No Docker required for unit tests — full CRUD, relationship, and query coverage in-process.
  - icon: 🔍
    title: Vector & fulltext search
    details: Native Vector KNN and fulltext search operations. Declare vector indexes in your model, query with .knn() — no raw Cypher needed.
---

## Quick look

```python
from runic.ogm import Field, Node, Repository, Session, create_driver

class Person(Node, labels=["Person"]):
    id: str = Field(index=True)
    name: str
    email: str = Field(index=True, unique=True)

driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")

with Session(driver) as session:
    session.add(Person(id="alice", name="Alice", email="alice@example.com"))
    session.commit()

    repo = Repository(session, Person)
    print(repo.count())   # 1
```

## Documentation

See the [OGM Quickstart](/ogm/quickstart) or [Migration Quickstart](/migration/quickstart) to get up and running.
