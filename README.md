<div align="center">
  <img src="https://raw.githubusercontent.com/jenreh/runic/refs/heads/main/docs/public/runic.svg" width="240" alt="Runic logo">

# Runic

**A type-safe OGM for Cypher graph databases.<br>
Define your models once, run them on any backend.**

![Version](https://img.shields.io/badge/version-0.3.6-blue)
[![PyPI](https://img.shields.io/pypi/v/runic-py.svg)](https://pypi.org/project/runic-py/)
[![Python](https://img.shields.io/badge/python-3.14%2B-orange)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)

[Why Runic](#why-runic) • [The OGM](#the-ogm) • [Migrations](#migrations) • [Installation](#installation) • [Docs](https://runic.rehpoehler.de)

</div>

---

Runic maps Python classes to graph nodes and edges. You declare typed `Node` and `Edge` models
and get change tracking, lazy and eager relationships, a composable query API, and schema
migrations — on top of a pluggable driver layer that runs the same model code on FalkorDB,
Neo4j, Memgraph, ArcadeDB, and Apache AGE.

## Why Runic

- **Backend-agnostic.** One model definition runs on five backends. Switching from FalkorDB to
  Neo4j means changing the arguments to `create_driver()`; your models, queries, and application
  code don't change.
- **Typed models, no metaclass magic.** `Node` and `Edge` are plain classes with typed `Field`
  descriptors — IDE autocomplete works, and `Author.name == "Alice"` builds a query predicate.
- **Change tracking.** Mutate an object and call `commit()`; the unit-of-work session computes
  the diff and writes only what changed. No manual dirty flags, no hand-written `SET` clauses.
- **First-class relationships.** Declare `Relation` fields for `INCOMING`/`OUTGOING` edges,
  with edge-property models, and choose lazy loading or single-round-trip eager fetch.
- **Native graph types.** `Vector` (vecf32), `GeoLocation` (point), interned strings, and
  automatic converters for `datetime` and `Enum` — stored without writing serialization code.
- **Migrations included.** A migration tool with versioned revisions, a CLI, and rollback
  snapshots. Revision state lives inside the graph, so there's no external state table.
- **Sync and async.** `Session`/`Repository` and `AsyncSession`/`AsyncRepository` share one API.

## The OGM

The two examples below build on one domain — `Author`, `Article`, and an `AUTHORED` edge —
and cover the features you'll reach for most.

### 1. Model a domain, persist it, and wire up relationships

Declare typed `Node` and `Edge` classes. Constraints and indexes go inline on `Field`; native
graph types (`Vector`, `GeoLocation`, `datetime`, `Enum`) get their converters assigned
automatically; and `Relation` declares a traversal with an optional edge-property model.
`SchemaManager` reconciles those declarations with the live graph, a `Session` handles writes
with automatic change tracking, and `session.relate()` creates the edges between nodes.

```python
from datetime import UTC, datetime
from enum import StrEnum

from runic.ogm import (
    Edge,
    Field,
    GeoLocation,
    Node,
    Relation,
    SchemaManager,
    Session,
    Vector,
    create_driver,
)


class Status(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class Article(Node, labels=["Article"]):
    id: str = Field(primary_key=True)
    title: str = Field(index_type="FULLTEXT")    # fulltext search: FalkorDB/Neo4j/Memgraph
    category: str = Field(interned=True)         # intern() dedup — FalkorDB only, no-op elsewhere
    status: Status = Status.DRAFT                # EnumConverter auto-assigned
    published_at: datetime | None = None         # DatetimeConverter auto-assigned
    embedding: Vector | None = None              # KNN via vecf32() on FalkorDB; Neo4j/Memgraph
                                                 #   need a pre-created VECTOR INDEX
    origin: GeoLocation | None = None            # point(); updates unsupported on ArcadeDB


class AuthoredEdge(Edge, type="AUTHORED"):
    created_at: datetime


class Author(Node, labels=["Author"]):
    id: str = Field(primary_key=True)
    email: str = Field(unique=True)
    name: str
    articles: list[Article] = Relation(
        relationship="AUTHORED",
        direction="OUTGOING",
        target="Article",
        edge_model=AuthoredEdge,
    )


# Pick a backend here — nothing else in this file changes.
driver = create_driver("falkordb", host="localhost", port=6379, graph="blog")

# Reconcile declared indexes/constraints with the live graph.
schema = SchemaManager(driver)
schema.sync_schema([Author, Article], drop_extra=False)  # create missing; keep extras

with Session(driver) as session:
    alice = Author(id="alice", email="alice@example.com", name="Alice")
    intro = Article(id="a1", title="Graphs 101", category="intro", status=Status.PUBLISHED)
    session.add_all([alice, intro])
    session.commit()

    # Create the AUTHORED edge, writing properties onto the relationship itself.
    # relate() is MERGE-based: idempotent, and re-calling updates the edge props.
    session.relate(alice, Author.articles, intro, edge=AuthoredEdge(created_at=datetime.now(UTC)))
    session.commit()

with Session(driver) as session:
    alice = session.get(Author, "alice")
    alice.name = "Alice Smith"   # tracked automatically — no explicit dirty flag
    session.commit()             # only the diff is written
```

### 2. Query and traverse the graph

Read data back with composable, type-safe statements, multi-hop traversals, paginated
repositories, or your own Cypher. `select()` builds a statement independently of any session,
so you can assemble it from conditional filters and reuse it across sessions. `.traverse()`
walks a single relationship; `.repeat()` walks one to any depth for real-world graph queries.

```python
from runic.ogm import Repository, Session, select


# Compose a query dynamically, then run it three ways.
stmt = select(Article).where(Article.status == Status.PUBLISHED)
if category:
    stmt = stmt.where(Article.category == category)

with Session(driver) as session:
    articles: list[Article] = session.scalars(stmt)  # list[Article]
    latest: Article | None = session.scalar(stmt)    # Article | None
    n: int = session.count(stmt)                      # int

    # Single-hop traversal with an edge-property filter — published articles
    # Alice authored after a cutoff date.
    recent = (
        session.query(Author)
        .alias("a")
        .where(Author.id == "alice")
        .traverse(Author.articles, edge_alias="e")
        .alias("art")
        .where(AuthoredEdge.created_at >= cutoff, on="e")
        .where(Article.status == Status.PUBLISHED, on="art")
        .return_target("art")
        .all()
    )

    # Variable-length traversal — every article reachable within 3 AUTHORED hops
    # (e.g. co-authorship chains). max_hops=None means unbounded.
    network = (
        session.query(Author)
        .alias("a")
        .where(Author.id == "alice")
        .repeat(Author.articles, min_hops=1, max_hops=3)
        .alias("reached")
        .all()
    )

    # Paginate through a repository.
    page = Repository(session, Article).find_all(skip=0, limit=20)

    # Or load relationships off an entity: lazy by default, eager on request.
    author = session.get(Author, "alice")
    author.articles                                   # lazy — queried on first access
    eager = session.get(Author, "alice", fetch=["articles"])
    eager.articles                                    # already loaded, no extra query


# Subclass Repository to drop down to typed Cypher when you need it.
class ArticleRepository(Repository[Article]):
    def by_author_email(self, email: str) -> list[Article]:
        return self.cypher(
            "MATCH (:Author {email: $email})-[:AUTHORED]->(a:Article) RETURN a",
            {"email": email},
            returns=Article,
        )
```

> [!TIP]
> Every pattern above has an async twin. `AsyncSession`, `AsyncRepository`, and
> `AsyncConnectionManager` share the same API for async-first applications.

---

## Migrations

`runic.migrate` is a migration tool with a CLI for versioned schema evolution. It stores
revision state inside the graph, so there's no external state table to manage.

```bash
runic init
runic revision -m "create user index"
```

Edit the generated file in `runic/versions/`:

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

**Baseline an existing graph** without re-running anything — introspect, generate a root
revision, and stamp it. The generated revision rebuilds the full schema on an empty graph,
so it's safe to replay for CI, cloning, or new tenants:

```bash
runic baseline -m "baseline"   # introspect, generate root revision, stamp it
runic current                  # verify it is now tracked
runic upgrade head             # rebuild full schema on a fresh graph
```

**Programmatic SDK** — drive migrations from code, against any backend:

```python
from pathlib import Path
from runic import Runic, init
from runic.migrate.adapters import create_adapter

init(Path("runic/"))

adapter = create_adapter(
    "falkordb", url="falkor://localhost:6379", graph_name="my_graph"
)
# adapter = create_adapter("neo4j", host="localhost", port=7687,
#                          database="neo4j", username="neo4j", password="secret")

runic = Runic(adapter, script_location=Path("runic/"))
runic.migrate.upgrade("head")
print("current:", runic.migrate.current())
```

---

## Installation

Install the core package plus the extra for your backend. The core has **no graph-driver
dependency** — you only pull in what you use.

| Backend | Extra | Driver installed |
| --- | --- | --- |
| FalkorDB | `falkordb` | `falkordb` |
| Neo4j | `neo4j` | `neo4j` |
| Memgraph | `memgraph` | `neo4j` (Bolt) |
| ArcadeDB | `arcadedb` | `neo4j` (Bolt) |
| Apache AGE | `age` | `psycopg[binary]` |
| All backends | `all` | all of the above |

```bash
uv add "runic-py[falkordb]"   # FalkorDB
uv add "runic-py[neo4j]"      # Neo4j
uv add "runic-py[memgraph]"   # Memgraph (Bolt)
uv add "runic-py[arcadedb]"   # ArcadeDB (Bolt)
uv add "runic-py[age]"        # Apache AGE (PostgreSQL extension)
uv add "runic-py[all]"        # everything
```

> [!NOTE]
> Runic requires Python 3.14+.

---

## Documentation

Full conceptual overview, async usage, advanced CLI flags, and the complete API reference live
at the **[Runic Documentation](https://runic.rehpoehler.de)**.

## License

Released under the [MIT License](LICENSE.md).
