<div align="center">
  <img src="https://raw.githubusercontent.com/jenreh/runic/refs/heads/main/docs/source/_static/runic.svg" width="240" alt="Runic logo">

# Runic

**Graph schema migrations and ORM for Cypher-based graph databases.**

![Version](https://img.shields.io/badge/version-0.2.2-blue)
[![Python](https://img.shields.io/badge/python-3.14%2B-orange)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)

[Features](#features) • [Installation](#installation) • [Migrations](#migrations) • [ORM](#runicorm) • [Documentation](#documentation)

</div>

---

**Runic** is a Python toolkit for Cypher-based graph databases that covers two layers:

- **`runic.migrate`** — Alembic-style schema migrations with revision tracking, a CLI, and rollback snapshots.
- **`runic.orm`** — A lightweight graph ORM: declare `Node` and `Edge` models, manage sessions, traverse relationships, and sync indexes — all via a pluggable driver layer supporting FalkorDB, ArcadeDB, and any Bolt-compatible database.

## Features

### Migration CLI

- **Alembic-Style Workflow** — Familiar CLI verbs: `init`, `revision`, `upgrade`, `downgrade`, `current`, `baseline`.
- **Graph-Native** — Migration state stored inside dedicated graph nodes (`:_FalkorMigrateVersion`).
- **Idempotent Cypher** — Explicit, guarded migration steps; safe to replay on an empty graph.
- **Offline & Dry Run** — Review generated Cypher scripts before running them in production.
- **Rollback Snapshots** — Uses `GRAPH.COPY` for high-risk, non-reversible migrations.

### Graph ORM

- **Declarative Models** — `Node` and `Edge` subclasses with typed `Field` descriptors; no metaclass magic.
- **Pluggable Driver Layer** — `GraphDriver` / `GraphDialect` protocols; built-in drivers for FalkorDB, ArcadeDB (via Bolt), and any Bolt-compatible DB. Switch backends without changing model code.
- **Session & Repository** — Unit-of-work session with change tracking; typed `Repository` for queries and pagination.
- **Relationships** — `Relation` field for INCOMING / OUTGOING edges; lazy and eager loading; edge property models.
- **Schema Management** — `IndexManager` and `SchemaManager` to create, validate, and sync RANGE, FULLTEXT, and UNIQUE indexes.
- **Native Graph Types** — First-class `Vector` (vecf32), `GeoLocation` (point), interned strings, and auto-converters for `datetime` and `Enum`.
- **Async Support** — `AsyncSession`, `AsyncRepository`, and `AsyncConnectionManager` for async-first applications.

## Installation

```bash
uv pip install runic
```

Or add it to an existing project:

```bash
uv add runic
```

> [!NOTE]
> Runic requires Python 3.14+ and is optimized for the latest FalkorDB clients.

---

## Migrations

Initialize your project and generate a new revision:

```bash
runic init
runic revision -m "create user index"
```

Open the generated file in `runic/versions/` and define your upgrade and downgrade:

```python
revision = "1975ea83b712"
down_revision = None


def upgrade(op) -> None:
    op.create_range_index("User", "email")


def downgrade(op) -> None:
    op.drop_range_index("User", "email")
```

Apply or roll back:

```bash
runic upgrade            # apply all pending revisions
runic downgrade          # roll back one step
runic downgrade 1975e    # roll back to a specific revision (prefix is enough)
```

### Baselining an existing graph

Bring an unmanaged FalkorDB graph under runic control without re-running anything:

```bash
runic baseline -m "baseline"   # introspect, generate root revision, stamp it
runic current                  # verify it is now tracked
```

The generated revision recreates all indexes from scratch — safe to replay on a fresh graph (CI, cloning, new tenants):

```bash
runic upgrade head   # rebuilds full schema on an empty graph
```

### Programmatic SDK

```python
from pathlib import Path
from runic import Runic, init
from runic.migrate.adapters import create_adapter

init(Path("runic/"))

adapter = create_adapter(
    "falkordb", url="falkor://localhost:6379", graph_name="my_graph"
)
runic = Runic(adapter, script_location=Path("runic/"))
runic.migrate.upgrade("head")

print("current:", runic.migrate.current())
```

---

## runic.orm

### Defining models

```python
from runic.orm import Field, Node, Edge, Relation


class User(Node, labels=["User"]):
    id: str
    email: str = Field(unique=True)
    name: str


class Post(Node, labels=["Post"]):
    id: str
    title: str = Field(index_type="FULLTEXT")
    published: bool = False


class AuthoredEdge(Edge, type="AUTHORED"):
    created_at: str  # ISO-8601


class Author(Node, labels=["Author"]):
    id: str
    name: str
    posts: list[Post] = Relation(
        relationship="AUTHORED",
        direction="OUTGOING",
        target="Post",
        edge_model=AuthoredEdge,
    )
```

### Session-based CRUD

`Session` accepts a `GraphDriver`.  Use the built-in helpers or `create_driver()`:

```python
from falkordb import FalkorDB
from runic.orm import FalkorDBDriver, Session, Repository

db = FalkorDB(host="localhost", port=6379)
graph = db.select_graph("myapp")
driver = FalkorDBDriver(graph)

with Session(driver) as session:
    session.add_all([
        User(id="alice", email="alice@example.com", name="Alice"),
        User(id="bob", email="bob@example.com", name="Bob"),
    ])
    session.commit()

with Session(driver) as session:
    repo = Repository(session, User)
    alice = session.get(User, "alice")
    alice.name = "Alice Smith"  # change tracking — no explicit dirty flag
    session.commit()

with Session(driver) as session:
    user = session.get(User, "bob")
    session.delete(user)
    session.commit()
```

**ArcadeDB** (via Bolt) uses the same session API — only the driver changes:

```python
from runic.orm import create_arcadedb_driver, Session

driver = create_arcadedb_driver(
    host="localhost", port=7687, database="mydb",
    username="root", password="playwithdata",
)
with Session(driver) as session:
    ...
```

### Relationships

```python
# Lazy load (default) — triggers a query on first access
with Session(driver) as session:
    author = session.get(Author, "alice")
    posts = author.posts  # query executed here

# Eager load — single round-trip
with Session(driver) as session:
    author = session.get(Author, "alice", fetch=["posts"])
    posts = author.posts  # already loaded, no extra query
```

### Pagination and custom queries

```python
from runic.orm import Pageable, Repository

with Session(driver) as session:
    repo = Repository(session, User)
    page = repo.find_all_paginated(Pageable(page=0, size=20, sort_by="name"))
    print(f"{len(list(page))} of {page.total_elements} total")
```

Extend `Repository` to add typed Cypher helpers:

```python
class UserRepository(Repository[User]):
    def find_by_email(self, email: str) -> User | None:
        return self.cypher_one(
            "MATCH (u:User {email: $email}) RETURN u",
            {"email": email},
            returns=User,
        )
```

### Schema management

Declare indexes inline on `Field`, then let `SchemaManager` keep the live graph in sync:

```python
from runic.orm import Field, IndexManager, Node, SchemaManager


class Place(Node, labels=["Place"]):
    id: str
    name: str = Field(index_type="FULLTEXT")
    slug: str = Field(unique=True)
    lat: float = Field(index=True)
    lon: float = Field(index=True)


schema = SchemaManager(driver)
schema.sync_schema([Place], drop_extra=False)  # create missing; leave extras alone

result = schema.validate_schema([Place])
print("valid:", result.is_valid)
```

### Native FalkorDB types

`Vector`, `GeoLocation`, `datetime`, and `Enum` fields get their converters assigned automatically — no `converter=` argument needed:

```python
from datetime import UTC, datetime
from enum import StrEnum
from runic.orm import Field, GeoLocation, Node, Vector


class Status(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class Article(Node, labels=["Article"]):
    id: str = Field(primary_key=True)
    category: str = Field(interned=True)  # intern() deduplication
    status: Status  # EnumConverter auto-assigned
    published_at: datetime | None = None  # DatetimeConverter auto-assigned
    embedding: Vector | None = None  # VectorConverter → vecf32()
    origin: GeoLocation | None = None  # GeoLocationConverter → point()
```

---

## Documentation

Full conceptual overview, async usage, advanced CLI flags, and API reference at the complete [Runic Documentation](https://runic-py.readthedocs.io/latest/).
