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
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-waypoints-icon lucide-waypoints"><circle cx="12" cy="4.5" r="2.5"/><path d="m10.2 6.3-3.9 3.9"/><circle cx="4.5" cy="12" r="2.5"/><path d="M7 12h10"/><circle cx="19.5" cy="12" r="2.5"/><path d="m13.8 17.7 3.9-3.9"/><circle cx="12" cy="19.5" r="2.5"/></svg>'
    title: Graph OGM
    details: Map Python classes to nodes and edges. Typed fields, indexes, constraints, lazy/eager relationships, and a fluent query builder.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-refresh-cw-icon lucide-refresh-cw"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M3 21v-5h5"/></svg>'
    title: Schema migrations
    details: Alembic-style versioned migration engine. Track index and constraint changes as replayable scripts with upgrade and downgrade paths.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-plug-icon lucide-plug"><path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/></svg>'
    title: Multi-backend
    details: Pluggable driver layer supports FalkorDB, ArcadeDB, Neo4j, Memgraph, and Apache AGE (PostgreSQL). Switch backends without rewriting models.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-zap-icon lucide-zap"><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>'
    title: Async first-class
    details: AsyncSession mirrors the sync API. No hidden lazy loads — deterministic query patterns for high-throughput applications.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-test-tube-diagonal-icon lucide-test-tube-diagonal"><path d="M21 7 6.82 21.18a2.83 2.83 0 0 1-3.99-.01 2.83 2.83 0 0 1 0-4L17 3"/><path d="m16 2 6 6"/><path d="M12 16H4"/></svg>'
    title: Testable by design
    details: Embedded FalkorDB via redislite. No Docker required for unit tests — full CRUD, relationship, and query coverage in-process.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-search-icon lucide-search"><path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/></svg>'
    title: Vector & fulltext search
    details: Native Vector KNN and fulltext search operations. Declare vector indexes in your model, query with .knn() — no raw Cypher needed.
---

## Quick look — OGM

Map classes to nodes, write a relationship, then traverse it with the
fluent query builder — no raw Cypher:

```python
from runic.ogm import Field, Node, Relation, Session, create_driver, select

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
    stmt = (
        select(Person).alias("p")
        .where(Person.id == "alice")
        .traverse(Person.friends).alias("f")
        .return_target("f")
    )
    friends: list[Person] = session.scalars(stmt)
    print([p.name for p in friends])   # ['Bob']
    # MATCH (p:Person) WHERE p.id = $p0
    # OPTIONAL MATCH (p)-[:FRIENDS]->(f:Person)
    # RETURN f
```

## Quick look — Migration

Track schema changes as versioned, replayable revision scripts. Generate
one with `runic revision`, then describe the change with `op.*` calls:

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

## There's more under the surface

These snippets barely scratch it. runic is built for the hard parts of
real graph work — the things you hit on day two, not day one:

- **Multi-hop and variable-length traversals** — chain `.traverse()` calls
  or use `.repeat(min_hops, max_hops)` to walk org charts, dependency
  trees, and recommendation paths without hand-writing `*1..5` Cypher.
- **Edge properties as first-class data** — model the relationship itself
  with `Edge`, read it back with `all_with_edges()`, and filter on the edge.
- **Lazy vs. eager loading, on your terms** — no hidden N+1 surprises;
  you decide what gets fetched and when.
- **Vector KNN and fulltext search** — declare the index on your model and
  query it with `.knn()` — native, not bolted on.
- **Async that mirrors the sync API** — the same calls, `await`-ed.
- **Migrations that travel** — the same `upgrade`/`downgrade` workflow runs
  unchanged across FalkorDB, ArcadeDB, Neo4j, Memgraph, and Apache AGE.

### Where to go next

Start with a quickstart and you'll have something running in five minutes:

- [OGM Quickstart](/ogm/quickstart) — model, query, and persist your first graph
- [Migration Quickstart](/migration/quickstart) — version your schema from zero

Then go deep:

- [Relationships](/ogm/relationships) — lazy/eager loading, `relate()`, edge properties
- [Query Builder](/ogm/query-builder) — traversals, aggregation, the Cypher behind every call
- [Async](/ogm/async) — the full async surface
- [Operations Reference](/migration/operations-reference) — every `op.*` call at a glance

> Bring your own backend. Write your models once. runic handles the Cypher.
