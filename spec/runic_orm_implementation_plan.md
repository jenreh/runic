# Custom FalkorDB OGM Framework — Implementation Plan

**Document Version**: 1.0
**Date**: June 5, 2026
**Status**: Ready for Implementation
**Scope**: Graph-optimized OGM replacement for `falkordb_orm`

---

## Executive Summary

Build a **lightweight, graph-optimized ORM** to replace the current `falkordb_orm` dependency in the Voyager project. The framework prioritizes:

- **SQLModel-style modeling** using `Node` and `Edge` base classes with class-level graph options
- **Clean architecture** inspired by SQLAlchemy/SQLModel (models → metadata → mapper → session → repository)
- **IDE-friendly fields** (`Field`-based, autocomplete support, see SQLModel/Pydantic)
- **Graph semantics first** (polymorphic nodes, multi-label support, native edge properties)
- **Explicit over implicit** (no magic `__getattr__` query resolution)
- **Sync + Async parity** (parallel APIs)

**Non-goals**: class decorators, migrations (solved by runic), querybuilder DSL, drop-in compatibility.

---

## Design Principles

### 1. Base Models + Fields as the Public API

- Graph models inherit from `Node` or `Edge`, similar to `SQLModel`
- Graph mapping options are declared on the class header, e.g. `class Country(Location, labels=["Location", "Country"], primary_label="Location")`
- `Field()` is the primary way to define properties, relationships, and indexes
- Type annotations are first-class, so IDE autocomplete and type checking work naturally

### 2. Graph Semantics Over SQL Analogs

- Relationships are edges with properties, not foreign keys
- Multi-label nodes represent graph categories, not table inheritance
- Polymorphic traversal (`target="Location"`) enables type-safe traversal of base classes
- No N+1 mitigation via joins; use eager loading + Cypher projections

### 3. Explicit Is Better Than Implicit

- Repository methods are defined, not derived via `__getattr__`
- Custom queries are normal repository methods that call explicit Cypher helpers
- No "magic" naming conventions for derived queries

### 4. Composition Over Inheritance

- Repositories are injected with a session and entity class
- Mappers are composed with metadata for encoding/decoding
- Sessions manage graph connections; repositories use sessions

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                   Application Layer                         │
├─────────────────────────────────────────────────────────────┤
│  Repository(session, Entity) ← typed reads + custom Cypher  │
│   ├─ find_all(fetch=[...])                                  │
│   ├─ find_all_by_ids([pk, ...], fetch=[...])                │
│   ├─ count()                                                │
│   ├─ exists(pk)                                             │
│   ├─ find_all_paginated(pageable)                           │
│   └─ cypher / cypher_one / cypher_raw                       │
├─────────────────────────────────────────────────────────────┤
│  Session / AsyncSession (Unit of Work)                      │
│   ├─ add(entity) / add_all([...])  ← pending → INSERT       │
│   ├─ delete(entity)                ← deleted → DETACH DELETE │
│   ├─ get(EntityClass, pk, fetch=[]) ← identity map + query  │
│   ├─ flush()   → executes pending writes to graph           │
│   ├─ commit()  → flush + clear pending set                  │
│   ├─ rollback() → discard un-flushed pending set            │
│   ├─ expire(entity) / refresh(entity)                       │
│   ├─ expunge(entity) / expunge_all()                        │
│   └─ identity map + object state tracking                   │
├─────────────────────────────────────────────────────────────┤
│  Mapper (Private, Composed in Session/Repository)           │
│   ├─ encode: entity → Cypher parameters (reads state flags) │
│   ├─ decode: Cypher result → entity (sets state flags)      │
│   └─ handles inheritance, eager loading                     │
├─────────────────────────────────────────────────────────────┤
│  MetaData (Registry for All Entities)                       │
│   ├─ tracks Node/Edge subclasses                            │
│   ├─ resolves string forward refs (e.g., target="Trip")     │
│   ├─ index declarations                                     │
│   └─ relationship metadata                                  │
├─────────────────────────────────────────────────────────────┤
│  ConnectionManager (sync/async pools)                       │
├─────────────────────────────────────────────────────────────┤
│  FalkorDB Graph Client (falkordb-py)                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Field Descriptor

**Purpose**: Unified descriptor for properties, relationships, and indexes.

**API**:

```python
from runic_orm import Edge, Field, Node

# Simple property
name: str = Field(default=None)

# Indexed property
email: str = Field(default=None, index=True)

# Unique constraint
code: str = Field(default=None, unique=True, required=True)

# Full-text search
bio: str = Field(default=None, index_type="FULLTEXT")

# Relationship (single)
company: Company | None = Field(
    relationship="WORKS_FOR", direction="OUTGOING", target="Company", cascade=True
)

# Relationship (collection)
employees: list["Person"] = Field(
    relationship="WORKS_FOR",
    direction="INCOMING",
    target="Person",
    lazy=True,  # default; False for eager
)

# Relationship with native edge properties
invited_trips: list["Trip"] = Field(
    relationship="INVITED_TO",
    direction="OUTGOING",
    target="Trip",
    edge_model="InvitationEdge",
)

# Generated ID
id: int | None = Field(generated=True)

# Manual ID
id: str = Field()

# With converter (for custom types like GeoPoint)
location: GeoPoint = Field(default=None, converter=GeoPointConverter())
```

**Parameters**:

| Parameter | Type | Description |
| --- | --- | --- |
| `default` | Any | Python default value |
| `index` | bool | Create RANGE index |
| `index_type` | str | Literal["FULLTEXT","VECTOR"] (semantic search hint) |
| `unique` | bool | Unique constraint |
| `required` | bool | Validates on save |
| `relationship` | str | Edge type string |
| `direction` | str | Literal["OUTGOING" ,"INCOMING", "BOTH"] |
| `target` | str/type | Entity class name (string or class) |
| `edge_model` | str/type | Optional `Edge` model storing edge properties |
| `cascade` | bool | Auto-save related entities |
| `lazy` | bool | Delay relationship loading (default True) |
| `converter` | TypeConverter | Custom encode/decode |
| `generated` | bool | FalkorDB auto-assigns node ID |

**Validation**:

- Mutually exclusive: `relationship` + `index`/`unique`
- `target` required for relationships
- `edge_model` must reference an `Edge` subclass when provided
- `converter` must implement `TypeConverter` interface

---

### 2. Node and Edge Base Classes

**Purpose**: Define graph nodes and relationship property models through base classes, matching the SQLModel style.

**API**:

```python
from runic_orm import Edge, Field, Node


# Simple node (single label)
class Person(Node, labels=["Person"]):
    id: int | None = Field(default=None, generated=True)
    name: str = Field()
    email: str = Field(index=True, unique=True)


# Multi-label node (polymorphic base)
class Location(Node, labels=["Location"], primary_label="Location"):
    id: str = Field()
    title: str = Field(index_type="FULLTEXT")
    latitude: float = Field(index=True)
    longitude: float = Field(index=True)


# Multi-label subtype
class Country(Location, labels=["Location", "Country"], primary_label="Location"):
    iso_code: str = Field(unique=True)
    population: int | None = Field(default=None)


# Multi-label subtype with inherited fields
class Museum(
    Location, labels=["Location", "Attraction", "Museum"], primary_label="Location"
):
    pass


# Edge model for relationship properties
class InvitationEdge(Edge, type="INVITED_TO"):
    role: str = Field(required=True)
    status: str = Field(required=True)
    invited_at: str = Field(required=True)
    accepted_at: str | None = Field(default=None)
```

**Behavior**:

- Reads all `Field` descriptors from class and parents
- Registers in global `metadata` registry
- Registers `Node` subclasses in node metadata and `Edge` subclasses in edge metadata
- Resolves string forward references after all models are imported
- Supports inheritance; child classes inherit parent fields
- `primary_label` determines polymorphic query root

**Object States**:

Each `Node` and `Edge` instance exists in exactly one state at any time, mirroring SQLAlchemy's model:

| State | How an object enters it |
| --- | --- |
| **Transient** | Created with `Entity(...)`, not yet known to any session |
| **Pending** | After `session.add(entity)`; will be INSERTed on `flush()` |
| **Persistent** | Loaded from the graph via `session.get()` or a Repository read; or after `flush()` of a pending entity |
| **Deleted** | After `session.delete(entity)`; will be `DETACH DELETE`d on `flush()` |
| **Detached** | After `session.expunge(entity)` or `session.close()`; no longer tracked |

Two private flags implement state detection:

- `_new: bool` — `True` until the first successful flush to the graph; drives CREATE vs MERGE in the Mapper
- `_dirty: bool` — `True` when any field is written on a persistent entity; drives MERGE/SET on the next flush

`Field.__set__` sets `_dirty = True` on write. The Mapper reads both flags; the Session clears `_dirty` after a successful `flush()`. Neither flag is part of the public API.

**Constraints**:

- One `primary_label` per class
- Forward refs (strings) resolve after module import / metadata finalization
- Circular refs allowed via string targets
- `Node.__init_subclass__` and `Edge.__init_subclass__` are the registration mechanism; no class decorators are part of the public modeling API

---

### 3. Repository

**Purpose**: Typed reads and custom Cypher queries for one entity type. Mutations (`add`, `delete`) and single-PK lookup (`get`) belong to the Session. Entities returned by Repository reads are automatically registered in the session's identity map.

**Constructor**:

```python
from runic_orm import Repository, Session

graph = db.select_graph("myapp")

with Session(graph) as session:
    people = Repository(session, Person)
```

#### Read

```python
# find_all — load all entities of this type
all_people = people.find_all()
all_people = people.find_all(fetch=["company"])

# find_all_by_ids — batch load by primary key
selected = people.find_all_by_ids([1, 2, 3])

# count
total = people.count()

# exists
exists = people.exists(1)
```

> **Single-entity lookup**: use `session.get(Person, pk)` — it checks the identity map before querying the graph.

#### Pagination

```python
from runic_orm import Pageable

pageable = Pageable(page=0, size=25, sort_by="name", direction="ASC")
page = people.find_all_paginated(pageable)

if page.has_next():
    next_page = people.find_all_paginated(pageable.next())

for person in page:
    print(person.name)
print(f"Page {page.page_number} of {page.total_pages}")
```

#### Custom Queries

```python
from runic_orm import Repository


class PersonRepository(Repository[Person]):
    def find_friends(self, person_id: int) -> list[Person]:
        return self.cypher(
            """
            MATCH (p:Person)-[:KNOWS]->(f:Person)
            WHERE p.id = $person_id
            RETURN f
            ORDER BY f.name ASC
            """,
            {"person_id": person_id},
            returns=Person,
        )

    def count_adults(self, min_age: int) -> int:
        return self.cypher_one(
            """
            MATCH (p:Person) WHERE p.age >= $min_age
            RETURN count(p)
            """,
            {"min_age": min_age},
            returns=int,
        )

    def deactivate(self, person_id: str) -> None:
        self.cypher(
            "MATCH (p:Person {id: $id}) SET p.active = false",
            {"id": person_id},
            write=True,
        )


# Usage
with Session(graph) as session:
    repo = PersonRepository(session, Person)
    friends = repo.find_friends(1)
    count = repo.count_adults(18)
```

**Custom Cypher Helpers**:

| Method | Returns | Description |
| --- | --- | --- |
| `cypher(query, params, returns, write)` | `list` | Entity/scalar rows |
| `cypher_one(query, params, returns, write)` | first value or `None` | Single result |
| `cypher_raw(query, params, write)` | raw `QueryResult` | Projections that must not be mapped |

| Parameter | Type | Description |
| --- | --- | --- |
| `query` | str | Cypher query string |
| `params` | dict | Query parameters passed to FalkorDB |
| `returns` | type | `Entity` class, `int`, `bool`, `str`, `dict`, or `None` |
| `write` | bool | Required `True` for CREATE / SET / DELETE queries |

---

### 4. Eager Loading & Relationships

**Pattern**: Pass `fetch=["relationship_name", ...]` to `session.get()` or Repository reads.

```python
# Lazy (default): relationship attribute triggers a graph query on access
person = session.get(Person, 1)
print(person.company)  # ← triggers graph query

# Eager: load in same Cypher query
person = session.get(Person, 1, fetch=["company", "friends"])
print(person.company)  # ← no additional query
```

**Implementation**: Mapper detects `fetch` list; builds Cypher with `OPTIONAL MATCH` for each named relationship.

---

### 5. Relationship with Edge Properties

**Pattern**: Relationship fields can declare properties on the edge itself.

```python
from runic_orm import Edge, Field, Node, Repository


class InvitationEdge(Edge, type="INVITED_TO"):
    role: str = Field(required=True)
    status: str = Field(required=True)
    invited_at: str = Field(required=True)  # ISO datetime
    accepted_at: str | None = Field(default=None)


class User(Node, labels=["User"]):
    id: str = Field(primary_key=True)
    invited_trips: list["Trip"] = Field(
        relationship="INVITED_TO",
        direction="OUTGOING",
        target="Trip",
        edge_model=InvitationEdge,
    )


class UserRepository(Repository[User]):
    def get_invitation_details(self, user_id: str, trip_id: str) -> dict | None:
        return self.cypher_one(
            """
            MATCH (u:User {id: $user_id})-[e:INVITED_TO]->(t:Trip {id: $trip_id})
            RETURN e.role AS role, e.status AS status, e.invited_at AS invited_at, e.accepted_at AS accepted_at
            """,
            {"user_id": user_id, "trip_id": trip_id},
            returns=dict,
        )
```

---

### 6. Session & AsyncSession

**Purpose**: Unit-of-work manager for FalkorDB. Owns all mutations (`add`, `delete`), single-entity lookup (`get`), identity map, and flush/commit lifecycle. Repositories hold a session reference and delegate writes and PK lookups to it.

#### FalkorDB Transaction Model

Source: [docs.falkordb.com/design/concurrency](https://docs.falkordb.com/design/concurrency.html)

| Level | Guarantee |
| --- | --- |
| **Single `GRAPH.QUERY`** | Fully atomic — either the entire query succeeds or the graph is unchanged. No partial writes are possible. |
| **Readers** | Snapshot isolation — each read sees the graph state at query-start; never sees in-progress writes from another query. |
| **Writers** | Serialized per graph via FIFO queue — only one write executes per graph at any moment. |
| **Multi-query** | No native transaction support. Use Redis `MULTI`/`EXEC` pipeline to guarantee that a batch of commands executes as an uninterrupted sequence without interleaving from other clients. |
| **Rollback** | Redis `MULTI`/`EXEC` is **not** a SQL-style rollback transaction. If one command in the batch fails after `EXEC`, earlier commands in the same batch are **not** reversed. |

**Design consequences for the Session**:

1. **`flush()` prefers single-query batching** — when all pending writes can be expressed as one Cypher statement (e.g. one `CREATE` with multiple nodes/edges), they are sent as a single atomic `graph.query()`.
2. **Multi-entity flush uses Redis `MULTI`/`EXEC`** — when a single Cypher cannot cover all pending writes, the session uses a Redis pipeline to send them as an uninterrupted block. This prevents interleaving from concurrent writers but does **not** roll back on partial failure.
3. **`generated=True` IDs break batching** — nodes with FalkorDB-assigned IDs must be created individually so the returned ID can be assigned back to the Python object. Client-assigned IDs (the recommended Voyager pattern) are pipeline-safe.
4. **`rollback()` is pre-flush only** — it discards the un-flushed pending/deleted sets. Once `flush()` has sent writes to the graph, they are permanent. The context manager calls `rollback()` on exception; it cannot undo already-executed writes.

#### SQLAlchemy Feature Parity

| SQLAlchemy Feature | Status | Notes |
| --- | --- | --- |
| `session.add(obj)` / `add_all` | **Adopted** | Core unit-of-work |
| `session.delete(obj)` | **Adopted** | Marks for `DETACH DELETE` on flush |
| `session.get(Entity, pk)` | **Adopted** | Identity map check → graph query |
| `session.flush()` | **Adopted** | Executes pending set; no server commit |
| `session.commit()` | **Adapted** | `flush()` + clear pending set; no server-side COMMIT |
| `session.rollback()` | **Adapted** | Discards un-flushed pending set only |
| `session.expire(obj)` | **Adopted** | Invalidate cached attrs; reload on access |
| `session.refresh(obj)` | **Adopted** | Immediate graph re-query |
| `session.expunge(obj)` / `expunge_all()` | **Adopted** | Remove from session; no graph action |
| Object states (transient/pending/persistent/deleted/detached) | **Adopted** | Direct mapping; see §2 |
| Identity map | **Adopted** | One instance per `(EntityClass, pk)` per session |
| `autobegin` | **Adopted** (default `True`) | Session starts tracking on first `add`/`delete` |
| `autoflush` | **Dropped** | Not meaningful without mid-transaction read-your-writes |
| `merge(obj)` | **Dropped** | Use Cypher `MERGE` via `cypher()` instead |
| `scoped_session` | **Dropped** | Use dependency injection |
| `execute(select(...))` | **Adapted** → `execute(cypher, params, write)` | Cypher query without entity mapping; returns raw `QueryResult` |

#### API

```python
from runic_orm import AsyncSession, Session

graph = db.select_graph("voyager")

# --- Sync ---

with Session(graph) as session:
    # add: transient → pending; INSERT on flush
    alice = Person(name="Alice", email="alice@example.com")
    session.add(alice)
    session.commit()  # flush → alice is now persistent
    print(alice.id)  # id assigned after flush

    # get: checks identity map first, then queries graph
    person = session.get(Person, alice.id)
    person.name = "Alice Smith"  # _dirty = True
    session.commit()  # MERGE/SET on flush

    # delete: persistent → deleted; DETACH DELETE on flush
    session.delete(person)
    session.commit()

    # expire / refresh
    session.expire(person)  # attrs cleared; reload on next access
    session.refresh(person)  # immediate re-query from graph

    # expunge: removes from session without graph action
    session.expunge(person)

    # execute: raw Cypher, no entity mapping
    result = session.execute(
        "MATCH (p:Person)-[:KNOWS]->(f:Person) WHERE p.id = $id RETURN f.name, f.email",
        {"id": "alice-id"},
    )
    for row in result.result_set:
        print(row[0], row[1])

    # execute write: bulk update not tied to a single entity type
    session.execute(
        "MATCH (t:Trip {status: $old}) SET t.status = $new",
        {"old": "draft", "new": "archived"},
        write=True,
    )

# Context manager auto-calls rollback() on exception
# (discards un-flushed pending set; cannot undo already-flushed writes)

# --- Explicit rollback (un-flushed writes only) ---
session = Session(graph)
try:
    session.add(Person(name="Bob", email="bob@example.com"))
    session.rollback()  # discards pending add; nothing written to graph
finally:
    session.close()

# --- Async ---
async with AsyncSession(graph) as session:
    alice = await session.get(Person, "alice-id")
    alice.email = "new@example.com"
    await session.commit()
```

**Session API**:

| Method | Description |
| --- | --- |
| `add(entity)` | Register transient/detached entity as pending |
| `add_all([entities])` | Batch `add` |
| `delete(entity)` | Mark persistent entity for `DETACH DELETE` on flush |
| `get(EntityClass, pk, fetch=[])` | Return from identity map or query graph; `None` if not found |
| `flush()` | Execute pending set against graph; clear `_dirty`; no semantic commit |
| `commit()` | `flush()` then clear pending/deleted sets |
| `rollback()` | Discard un-flushed pending/deleted sets; expire persistent entities |
| `expire(entity)` | Invalidate cached attributes; reloaded on next field access |
| `refresh(entity)` | Immediately re-query entity from graph |
| `expunge(entity)` | Remove entity from session (→ detached); no graph action |
| `expunge_all()` | Expunge all tracked entities |
| `execute(cypher, params, write)` | Execute raw Cypher; returns `QueryResult`; no entity mapping |
| `close()` | `expunge_all()` + release connection |

**Identity Map**:

- Keyed by `(EntityClass, pk)` — one Python instance per primary key per session
- `session.get()` and all Repository reads register loaded entities
- `expire()` clears attribute cache without removing from map; next field access triggers a graph query
- `rollback()` expires all persistent entities (attributes reloaded on next access)
- `close()` expunges all entries

**Flush Strategy**:

```text
session.flush() / session.commit()

  Case 1 — single entity or all writes expressible as one Cypher:
    → single graph.query(combined_cypher)   ← fully atomic

  Case 2 — multiple entities, client-assigned IDs:
    → pipeline = graph.pipeline()           ← Redis MULTI/EXEC
    → pipeline.query(cypher_1)
    → pipeline.query(cypher_2)  ...
    → pipeline.execute()                    ← uninterrupted sequence; no auto-rollback on partial failure

  Case 3 — entity has generated=True ID:
    → individual graph.query() per entity   ← ID returned and assigned before next write

  After successful flush:
    → each flushed entity: _new = False, _dirty = False
    → deleted entities removed from identity map
    → all tracking sets cleared
```

#### AsyncSession

Mirrors the Session API exactly; all methods are `async`. Use `async with AsyncSession(graph) as session:`.

```python
async with AsyncSession(graph) as session:
    repo = AsyncRepository(session, Trip)
    trips = await repo.find_all()
    for trip in trips:
        trip.status = "archived"
    await session.commit()
```

---

### 7. Index & Schema Management

**Purpose**: Validate declared indexes against FalkorDB; create/sync as needed.

```python
from runic_orm import IndexManager, SchemaManager

# IndexManager: apply index declarations
manager = IndexManager(graph)
manager.create_indexes(Person, if_not_exists=True)
manager.ensure_indexes(Trip)

# SchemaManager: validate + sync
schema = SchemaManager(graph)
result = schema.validate_schema([Person, Trip, Stop])

if not result.is_valid:
    print(result.missing_indexes)
    print(result.extra_indexes)
    schema.sync_schema([Person, Trip, Stop], drop_extra=False)
```

**SchemaManager API**:

`validate_schema` returns a result object with `is_valid: bool`, `missing_indexes: list`, `extra_indexes: list`, and `errors: list`.

```python
result = schema.validate_schema([Entity1, Entity2, ...])

# create missing indexes
schema.sync_schema([Entity1, Entity2, ...], drop_extra=False)

# human-readable diff
diff = schema.get_schema_diff([Entity1, Entity2, ...])

# diagnostics
info = schema.get_schema_info([Entity1, Entity2, ...])
```

---

## API Examples

### Example 1: Simple CRUD

```python
from runic_orm import Field, Node, Repository, Session


class Language(Node, labels=["Language"]):
    id: str = Field()
    title: str = Field()
    code: str = Field(unique=True, required=True)


graph = db.select_graph("voyager")

with Session(graph) as session:
    languages = Repository(session, Language)

    # Create — session.add() stages the insert
    lang = Language(id="en", title="English", code="en-US")
    session.add(lang)
    session.commit()  # flush → lang is now persistent

    # Read all
    all_langs = languages.find_all()

    # Read one — identity map check before graph query
    en = session.get(Language, "en")

    # Update — Field.__set__ marks en._dirty = True; committed on flush
    en.title = "English (US)"
    session.commit()

    # Delete
    session.delete(en)
    session.commit()
```

### Example 2: Polymorphic Location Hierarchy

```python
from runic_orm import Field, Node, Repository


class Location(Node, labels=["Location"], primary_label="Location"):
    id: str = Field()
    title: str = Field(index_type="FULLTEXT")
    latitude: float = Field(index=True)
    longitude: float = Field(index=True)
    description: str = Field(index_type="FULLTEXT")


class Country(Location, labels=["Location", "Country"], primary_label="Location"):
    iso_code: str = Field(unique=True)
    capital: str | None = Field(default=None)
    population: int | None = Field(default=None)


class City(Location, labels=["Location", "City"], primary_label="Location"):
    population: int | None = Field(default=None)


class Restaurant(Location, labels=["Location", "Restaurant"], primary_label="Location"):
    cuisine: str | None = Field(default=None)


graph = db.select_graph("voyager")

with Session(graph) as session:
    locations = Repository(session, Location)

    # Find all locations (returns mix of Country, City, Restaurant)
    all_locs = locations.find_all()
    for loc in all_locs:
        print(f"{loc.__class__.__name__}: {loc.title}")

    # Find specific subtype — session.get for a single PK lookup
    countries = Repository(session, Country)
    france = session.get(Country, "FR")  # only [Location, Country] nodes
```

### Example 3: Relationships & Cascade

```python
class Company(Node, labels=["Company"]):
    id: int | None = Field(default=None, generated=True)
    name: str = Field()


class Person(Node, labels=["Person"]):
    id: int | None = Field(default=None, generated=True)
    name: str = Field()
    email: str = Field(index=True, unique=True)
    company: Company | None = Field(
        relationship="WORKS_FOR",
        direction="OUTGOING",
        target="Company",
        cascade=True,  # auto-save company when person is saved
    )


with Session(graph) as session:
    # cascade=True: session.add(person) also stages company for insert
    company = Company(name="Acme")
    person = Person(name="Alice", email="alice@acme.com", company=company)
    session.add(person)
    session.commit()

    assert person.id is not None
    assert company.id is not None  # auto-added via cascade
```

### Example 4: Pagination

```python
from runic_orm import Pageable, Session

with Session(graph) as session:
    trips = Repository(session, Trip)

    # First page
    pageable = Pageable(page=0, size=50, sort_by="title", direction="ASC")
    page = trips.find_all_paginated(pageable)

    print(f"Total: {page.total_elements}, Pages: {page.total_pages}")
    for trip in page:
        print(trip.title)

    # Next page
    if page.has_next():
        next_page = trips.find_all_paginated(pageable.next())
```

---

## Module Structure

```text
runic_orm/
├── __init__.py
│   └── exports: Node, Edge, Field, Repository, AsyncRepository, Pageable,
│       Session, AsyncSession, IndexManager, SchemaManager, metadata
├── core/
│   ├── descriptors.py (Field descriptor — sets _dirty on __set__)
│   ├── models.py (Node and Edge base classes — _dirty, _new flags)
│   ├── metadata.py (global metadata registry, entity tracking)
│   └── types.py (Pageable, Page, TypeConverter, etc.)
├── mapper/
│   ├── mapper.py (Mapper class: encode/decode; reads _dirty/_new)
│   ├── relationship_loader.py (lazy/eager loading logic)
│   └── converter.py (TypeConverter interface + defaults)
├── repository/
│   ├── repository.py (Repository base class — takes Session)
│   ├── async_repository.py (AsyncRepository — takes AsyncSession)
│   ├── cypher.py (explicit Cypher helper methods and result mapping)
│   └── pagination.py (Pageable, Page)
├── schema/
│   ├── index_manager.py (IndexManager — takes graph, not Session)
│   └── schema_manager.py (SchemaManager — takes graph, not Session)
├── session/
│   ├── session.py (Session: add/delete/get/flush/commit/rollback/expire/refresh/expunge, identity map)
│   ├── async_session.py (AsyncSession: async parity)
│   └── connection_pool.py (ConnectionManager: sync/async pools)
└── exceptions.py (RepositoryException, EntityNotFound, DetachedEntityError, etc.)
```

---

## Implementation Phases

### Phase 1: Core Foundation

1. **Model System** (`Node`, `Edge`, `Field`, metadata registry)
    - Implement `Field` descriptor with IDE autocomplete support
    - `Field.__set__` sets `entity._dirty = True` and registers the entity in the active session's dirty set
    - `Node` and `Edge` carry `_dirty: bool` and `_new: bool` instance flags; `_new = True` on construction, `False` after decode from graph
    - Implement `Node.__init_subclass__` and `Edge.__init_subclass__` for SQLModel-style class registration
    - Build metadata registry: tracks all entities, relationships, string forward refs

2. **Type System & Converters**
   - `TypeConverter` interface (to_graph, from_graph)
   - Built-in converters for common types (datetime, enum, etc.)
   - Support custom converters (e.g., GeoPoint)

### Phase 2: Session & Unit-of-Work

> **FalkorDB transaction model** (verified from docs): single `GRAPH.QUERY` is fully atomic (all-or-nothing, snapshot-isolated reads, serialized writes). Multi-query uses Redis `MULTI`/`EXEC` pipeline — commands execute as an uninterrupted sequence but do not roll back on partial failure. `rollback()` discards the un-flushed pending set only; cannot undo sent writes.

1. **Session** (sync)
   - Constructor: `Session(graph)` — wraps the FalkorDB graph handle; `autobegin=True`
   - `add(entity)` / `add_all([...])` — transient/detached → pending
   - `delete(entity)` — persistent → deleted
   - `get(EntityClass, pk, fetch=[])` — identity map check → graph query; returns `None` if not found
   - `flush()` — executes pending/dirty/deleted sets using the flush strategy:
     - One entity or single-Cypher-expressible batch → single `graph.query()` (atomic)
     - Multiple entities with client IDs → Redis `MULTI`/`EXEC` pipeline
     - Entities with `generated=True` IDs → individual queries (ID must be returned before proceeding)
   - `commit()` — `flush()` + clear all tracking sets
   - `rollback()` — discard un-flushed pending/deleted sets; expire persistent entities; cannot undo sent writes
   - `execute(cypher, params={}, write=False)` — raw Cypher, no entity mapping; returns `QueryResult`; bypasses identity map
   - `expire(entity)` — invalidate attribute cache; reloaded on next field access
   - `refresh(entity)` — immediate re-query from graph
   - `expunge(entity)` / `expunge_all()` — remove from session (→ detached)
   - `close()` — `expunge_all()` + release connection
   - Context manager: `__exit__` calls `commit()` on success, `rollback()` on exception
   - Identity map: `dict[(EntityClass, pk), entity]`

2. **AsyncSession** (async parity)
   - All Session methods `async`; `async with AsyncSession(graph) as session:`

3. **ConnectionManager** (sync/async pools)
   - Manages a pool of graph connections
   - `Session` and `AsyncSession` acquire/release from pool

### Phase 3: Mapper & Object Lifecycle

1. **Mapper** (encode Python objects ↔ Cypher parameters/results)
   - Encode: `_new = True` → `CREATE`; `_dirty = True` → `MERGE … SET`
   - Encode deleted: `DETACH DELETE`
   - Decode: Cypher result rows → entity instances; set `_new = False`, `_dirty = False`
   - Collect all fields from class + parents (inheritance)

2. **Relationship Loading** (lazy + eager)
   - Lazy: descriptor triggers a graph query on attribute access
   - Eager: `fetch=[...]` on `session.get()` and Repository reads; builds multi-`OPTIONAL MATCH` Cypher
   - Resolver for string forward refs (`target="Location"`) during metadata finalization

### Phase 4: Repository & Reads

1. **Base Repository** (sync)
   - Constructor: `Repository(session, EntityClass)`
   - Read methods: `find_all(fetch=[])`, `find_all_by_ids([pk, ...], fetch=[])`, `count()`, `exists(pk)`, `find_all_paginated(pageable)`
   - All reads register returned entities in the session identity map
   - No mutation methods — mutations belong to Session (`add`, `delete`)
   - No `find_by_id` — use `session.get(EntityClass, pk)` instead

2. **Explicit Cypher Helpers**
   - `cypher(query, params, returns, write)` → list
   - `cypher_one(query, params, returns, write)` → first value or `None`
   - `cypher_raw(query, params, write)` → raw `QueryResult`
   - `write=True` required for Cypher writes; entities returned from reads are registered in identity map

3. **AsyncRepository** (parallel API)
   - Constructor: `AsyncRepository(async_session, EntityClass)`
   - Same read methods + Cypher helpers, all async

### Phase 5: Pagination & Querying

1. **Pagination**
   - `Pageable` class (page, size, sort_by, direction)
   - `Page[T]` class (items, page_number, total_pages, total_elements, has_next, has_previous, etc.)
   - `find_all_paginated(pageable) → Page[T]`
   - Navigation helpers: `pageable.next()`, `.previous()`, `.first()`

### Phase 6: Schema Management

1. **IndexManager** (create indexes; binds to graph, not Session)
   - Reads `index=True`, `index_type=FULLTEXT`, `unique=True` from Field descriptors
   - `create_indexes(Entity, if_not_exists=True)`
   - `ensure_indexes(Entity)`

2. **SchemaManager** (validate + sync; binds to graph, not Session)
    - `validate_schema([Entity, ...]) → result` with `missing_indexes`, `extra_indexes`, `is_valid`, `errors`
    - `sync_schema([Entity, ...], drop_extra=False)` to create missing
    - `get_schema_diff([Entity, ...])` for human-readable diff
    - `get_schema_info([Entity, ...])` for diagnostics

### Phase 7: Testing & Docs

1. **Test Suite** (unit + integration + async)
    - Unit: Field (dirty marking), Node/Edge (_dirty/_new flags), Mapper, Metadata, Session lifecycle
    - Integration: Session commit/rollback, Repository CRUD, eager loading, relationships, pagination, explicit Cypher helpers
    - Async: AsyncSession + AsyncRepository methods
    - Voyager patterns: Location polymorphism, User/Trip hierarchy, InvitationEdge

2. **Documentation & Examples**
    - README with architecture diagram
    - Usage examples (simple CRUD, session transactions, polymorphic nodes, edge properties, pagination, custom queries)
    - Voyager migration guide (swap `falkordb_orm` → `runic_orm`)

---

## Constraints & Non-Goals

### Constraints

- **No Pydantic**: Plain Python with descriptors only
- **No SQLAlchemy Core**: Fresh design optimized for graphs
- **No migrations**: Use Runic (external tool) for schema versioning
- **No class or method decorators**: `Node`/`Edge` base classes and explicit repository methods are the public API
- **No DSL querybuilder**: Cypher is first-class via repository helpers
- **No generated methods**: `find_by_*` derive via `__getattr__` is **not** supported
- **Session owns mutations**: `session.add()` / `session.delete()` / `session.get()` — no save/delete on Repository
- **Single-query atomicity**: prefer batching multiple entity writes into one Cypher query for true atomicity (FalkorDB guarantee)
- **Multi-query pipeline**: fall back to Redis `MULTI`/`EXEC` for multi-entity writes; guarantees sequence, not SQL-style rollback
- **`rollback()` is pre-flush only**: discards un-flushed pending set; cannot undo writes already sent to the graph
- **No `autoflush`**: not meaningful without mid-transaction read-your-writes in FalkorDB

### Non-Goals

- Multi-database support (FalkorDB only)
- Query caching or result buffering
- Automatic N+1 detection
- ORM-level encryption (use FalkorDB's built-ins)
- Distributed or cross-graph transactions
- `session.merge()` — use Cypher `MERGE` via `cypher()` instead
- `scoped_session` / thread-local session management

---

## Key Voyager Patterns to Support

- **Polymorphic traversal**: `class Location(Node, labels=["Location"], primary_label="Location")` + `target="Location"` in relationships
- **Multi-label inheritance**: `class Country(Location, labels=["Location", "Country"], primary_label="Location")`
- **Edge properties**: Relationships declare `edge_model=InvitationEdge`; explicit repository methods read/write them
- **Timestamp convention**: ISO-8601 strings (no FalkorDB `localdatetime`)
- **Lazy relationships**: `list["Trip"]` vs `"Trip"` (string forward ref resolves during metadata finalization)
- **Session-scoped mutations**: `session.add()` / `session.delete()` stage all writes; `session.commit()` executes them sequentially — no Repository mutation methods

---

## Testing Strategy

### Scope

1. **Unit tests**: Field dirty marking, Node/Edge flags, Mapper encode/decode paths, Metadata
2. **Session tests**: begin/commit/rollback lifecycle, identity map, flush, AsyncSession parity
3. **Integration tests**: Repository CRUD, eager loading, relationships, pagination, explicit Cypher helpers
4. **Schema tests**: IndexManager, SchemaManager validate + sync
5. **Example tests**: Verify Voyager node patterns work (Location hierarchy, InvitationEdge)

### Test Structure

```text
tests/
├── unit/
│   ├── test_field.py          (dirty marking, Field.__set__)
│   ├── test_node.py           (_dirty/_new flags, registration)
│   ├── test_edge.py
│   ├── test_mapper.py         (encode/decode, _new vs _dirty path)
│   └── test_metadata.py
├── session/
│   ├── test_session.py        (begin/commit/rollback, identity map, flush)
│   └── test_async_session.py
├── integration/
│   ├── test_repository_crud.py
│   ├── test_relationships.py
│   ├── test_eager_loading.py
│   ├── test_pagination.py
│   └── test_cypher_helpers.py
├── schema/
│   ├── test_index_manager.py
│   └── test_schema_manager.py
├── async/
│   └── test_async_repository.py
└── fixtures.py (mock graph, test entities)
```

### Example Entities for Testing

- `Location`, `Country`, `City`, `Restaurant` (polymorphic)
- `User`, `Trip`, `TripDay`, `Stop` (complex relationships)
- `InvitationEdge` pattern (edge properties)

---

## Success Criteria

### Session

- [ ] `session.add()` / `session.add_all()` move transient entities to pending
- [ ] `session.delete()` marks persistent entities for `DETACH DELETE` on flush
- [ ] `session.get(EntityClass, pk)` checks identity map before querying graph; returns `None` if absent
- [ ] `session.flush()` executes pending/dirty/deleted sets as Cypher writes; does not clear identity map
- [ ] `session.commit()` = `flush()` + clear pending/deleted sets
- [ ] `session.rollback()` discards un-flushed pending/deleted sets; expires persistent entities
- [ ] `session.expire(entity)` invalidates attribute cache; re-queried on next field access
- [ ] `session.refresh(entity)` immediately re-queries from graph
- [ ] `session.execute(cypher, params, write)` runs raw Cypher and returns `QueryResult` without entity mapping
- [ ] `session.expunge(entity)` removes entity from session (→ detached); no graph action
- [ ] Context manager commits on success, rolls back on exception
- [ ] Identity map returns the same instance on repeated loads within a session
- [ ] `AsyncSession` mirrors all of the above asynchronously

### Object States & Dirty Tracking

- [ ] Entities pass through: transient → pending → persistent; persistent → deleted; persistent → detached
- [ ] `Field.__set__` marks `_dirty = True` on persistent entities
- [ ] `_new = True` on construction; `False` after first successful flush
- [ ] Mapper uses CREATE for `_new`, MERGE/SET for `_dirty`, DETACH DELETE for deleted
- [ ] `_dirty` cleared after successful `flush()`

### Repository

- [ ] `Repository` constructor takes `Session`; `AsyncRepository` takes `AsyncSession`
- [ ] No mutation methods on Repository — all mutations go through Session
- [ ] `find_all(fetch=[])`, `find_all_by_ids([...])`, `count()`, `exists(pk)` work correctly
- [ ] All Repository reads register returned entities in the session identity map
- [ ] `find_all_paginated(pageable)` returns `Page[T]`
- [ ] `cypher` / `cypher_one` / `cypher_raw` helpers work for sync + async

### Eager Loading

- [ ] `session.get(EntityClass, pk, fetch=["rel"])` loads related entities in one Cypher query
- [ ] Repository `find_all(fetch=[...])` works for single + collection relationships

### Graph Semantics

- [ ] Polymorphic nodes (primary_label) work correctly
- [ ] Multi-label inheritance works (child inherits parent fields)
- [ ] Lazy loading resolves string forward refs
- [ ] Circular type refs don't break

### Field Descriptors

- [ ] IDE autocomplete works on Field parameters
- [ ] Index types (RANGE, FULLTEXT, VECTOR) map correctly to FalkorDB
- [ ] Unique + Required validation works

### Schema Management

- [ ] IndexManager creates missing indexes
- [ ] SchemaManager validates + syncs
- [ ] Extra indexes detected correctly

### Voyager Compatibility

- [ ] Current nodes.py concepts work after converting decorators to `Node` base classes
- [ ] Edge properties (InvitationEdge) persist natively
- [ ] Relationship inheritance (Location → Country) transparent
- [ ] All ~30 node types work (User, Trip, Stop, Location subtypes, etc.)

### Code Quality

- [ ] No f-strings in logging
- [ ] Type annotations on all public methods
- [ ] Test coverage ≥ 80% on non-test code
- [ ] Docstrings on all public classes/methods

---

## Delivery Checklist

- [ ] Fully functional implementation
- [ ] Comprehensive test suite (unit + integration)
- [ ] Usage documentation (README + examples)
- [ ] Voyager migration guide (how to swap `falkordb_orm` decorators → `runic_orm` base classes)
- [ ] Performance baseline (simple queries, pagination)
- [ ] Async examples + tests

---

## Further Considerations

### 1. IDE Autocomplete

Ensure Field parameters show up in editor tooltips & completion

- Use `__init__` type hints on Field
- Test with VSCode/PyCharm

### 2. Backward Compatibility

If Voyager needs gradual migration, wrap old `falkordb_orm` calls as adapters (post-Phase 3)

### 3. Performance Tuning

Consider connection pooling, query result caching, lazy loading batching (Phase 5 optimization)

---
