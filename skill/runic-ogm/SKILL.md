---
name: runic-ogm
description: |
  Expert guide for runic.ogm — a SQLModel-style, graph-native Python OGM for
  Cypher databases (FalkorDB, Neo4j, Memgraph, ArcadeDB, Apache AGE). Use
  whenever the user defines graph models (Node/Edge), maps fields, declares
  relationships, writes graph queries/traversals, or does session/repository
  CRUD with runic. Invoke for any code that imports from `runic.ogm`, uses
  `Node`, `Edge`, `Field`, `Relation`, `Session`, `Repository`, `select()`, or
  the query builder, and for any "how do I model/query this graph in runic"
  task. This is the OGM skill; for schema migrations use the `runic-migrate`
  skill instead.
---

# runic.ogm — Graph OGM for Cypher Databases

`runic.ogm` is a lightweight, SQLModel-inspired OGM for property-graph
databases. You declare nodes and edges as typed Python classes, then create,
read, relate, and query them through a `Session` — without hand-writing Cypher.
It targets **FalkorDB** first and also runs on **Neo4j, Memgraph, ArcadeDB, and
Apache AGE** through a pluggable driver layer.

Three pillars, each with a runnable example and a reference:

| Pillar | What it covers | Start here |
|---|---|---|
| **Mapping** | `Node`/`Edge` classes, `Field()`, defaults, PK, indexes, native types | [examples/mapping.py](examples/mapping.py) |
| **Relations** | `Relation()`, lazy/eager loading, edge models, `relate()`, polymorphism | [examples/relations.py](examples/relations.py) |
| **Query builder** | `select()`, filters, traversal, aggregation, search | [examples/query_builder.py](examples/query_builder.py) |

For the full API surface (every `Field`/`Relation` parameter, all `Session`,
`Repository`, and `QueryBuilder` methods, drivers, exceptions) read
[references/api-reference.md](references/api-reference.md). For task-oriented
recipes and gotchas read [references/cookbook.md](references/cookbook.md).

> The snippets below omit the `# type: ignore` / `# noqa` comments the repo's
> own examples carry. Those exist only because `Field()`/`Relation()` return
> `Any` and the descriptor comparison operators (`User.age > 18`) confuse some
> type checkers. The code is correct as written; add the ignores only if your
> checker complains.

---

## Quick start

> **All runic.ogm imports come from `runic.ogm` directly.** `Session`,
> `Repository`, `select`, and their methods (`add`, `commit`, `flush`,
> `scalars`, `relate`, `unrelate`, `query`, `count`, `all_rows`, etc.) are
> **runic.ogm-native API** — not from SQLAlchemy or any other ORM. Never
> import from `runic.ogm.orm.*` — the package root re-exports everything.

```python
from runic.ogm import (
    Field, Node, Edge, Relation,
    Session, AsyncSession,
    Repository,
    select,
    count, avg, sum_,
)
from runic.ogm.driver.factory import create_driver

class User(Node, labels=["User"]):
    id: str = Field(primary_key=True)
    name: str
    email: str = Field(unique=True)
    active: bool = True

driver = create_driver("falkordb", host="localhost", port=6379, graph="app")

with Session(driver) as session:
    session.add(User(id="u1", name="Alice", email="alice@example.com"))
    session.commit()

    alice = session.get(User, "u1")     # read by primary key
    alice.name = "Alice B."             # mutation marks the entity dirty
    session.commit()                    # flushes the SET automatically

driver.close()
```

Embedded FalkorDB (no server, great for tests/examples):

```python
from redislite import FalkorDB
from runic.ogm.driver.falkordb import FalkorDBDriver

db = FalkorDB(protocol=2)               # protocol=2 avoids a redis-py 8 issue
driver = FalkorDBDriver(db.select_graph("app"))
```

---

## Mapping: defining models

A **Node** is a vertex; declare it with a `labels` list. An **Edge** is a
relationship *property* model; declare it with a `type` string.

```python
from datetime import datetime
from enum import StrEnum
from runic.ogm import Edge, Field, Node, Vector, GeoLocation

class Status(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"

class Article(Node, labels=["Article"]):
    id: str = Field(primary_key=True)        # explicit PK
    title: str                               # bare annotation → required field
    summary: str | None = None               # optional → defaults to None
    status: Status                            # Enum → EnumConverter auto-applied
    published_at: datetime | None = None      # datetime → DatetimeConverter auto
    country: str = Field(interned=True)        # intern() dedup (FalkorDB)
    embedding: Vector | None = None           # vecf32() vector (FalkorDB)
    origin: GeoLocation | None = None         # point() geo (FalkorDB)
    views: int = Field(default=0)

class Authored(Edge, type="AUTHORED"):       # edge property model
    at: datetime
    primary: bool = Field(default=False)
```

**Field declaration — two equivalent styles.** A bare annotation
(`title: str`) is auto-promoted to a `Field`. Use the explicit `Field(...)` form
only when you need options: `primary_key`, `unique`, `index`, `index_type`,
`default`, `default_factory`, `converter`, `interned`, `generated`. See the full
parameter table in [references/api-reference.md](references/api-reference.md).

**Best practices for mapping:**

- **Pick the primary key deliberately.** `Field(primary_key=True)` is explicit
  and clearest. A field named `id` is treated as the PK by convention if none is
  marked. For DB-generated identifiers use `Field(generated=True)`.
- **Constructors are keyword-only.** Always `Article(id="a1", title="…")`, never
  positional. Unknown kwargs and missing required fields raise `TypeError`.
- **Let auto-converters work.** `datetime`, `Enum`, `Vector`, and `GeoLocation`
  fields get the right `TypeConverter` automatically — don't pass `converter=`
  for these. Explicit `converter=` always wins if you need custom behavior.
- **Native types are FalkorDB-specific.** `Vector` (`vecf32`), `GeoLocation`
  (`point`), and `interned=True` (`intern`) are wrapped only on FalkorDB; other
  backends store the raw value. See [examples/native_types.py](examples/native_types.py).
- **Indexes:** `Field(index=True)` for a range index, `Field(unique=True)` for a
  uniqueness constraint, `Field(index_type="FULLTEXT")` / `="VECTOR"` to back
  search. The declarations live on the model; actual index *creation* is done by
  `runic.migrate`'s `IndexManager` (see the `runic-migrate` skill).

**Polymorphism** uses multi-label nodes with a shared `primary_label`. A query
on the base class returns the correct concrete subtypes:

```python
class Location(Node, labels=["Location"], primary_label="Location"):
    id: str
    title: str

class City(Location, labels=["Location", "City"], primary_label="Location"):
    population: int | None = None
```

`Repository(session, Location).find_all()` returns a mix of `City`, etc., each
as its concrete type. Full example: [examples/polymorphism.py](examples/polymorphism.py).

---

## Relations: connecting nodes

Declare a relationship with `Relation()`. `relationship`, `direction`, and
`target` are required; `edge_model` attaches a property model.

```python
from runic.ogm import Node, Relation

class User(Node, labels=["User"]):
    id: str = Field(primary_key=True)
    name: str
    # single related node
    manager: "User | None" = Relation(
        relationship="REPORTS_TO", direction="OUTGOING", target="User"
    )
    # collection, with edge properties
    articles: list["Article"] = Relation(
        relationship="AUTHORED", direction="OUTGOING",
        target="Article", edge_model="Authored",
    )
    # symmetric / undirected
    contacts: list["User"] = Relation(
        relationship="KNOWS", direction="BOTH", target="User"
    )
```

**Reading relationships — lazy vs eager:**

```python
# Lazy (default): first attribute access runs a query. Needs a live session.
user = session.get(User, "u1")
for a in user.articles:        # triggers the load here
    ...

# Eager: fetch alongside the parent in one query — no later round-trips.
user = session.get(User, "u1", fetch=["articles"])
```

**Mutating relationships** — use `relate()` / `unrelate()` instead of raw
Cypher. `relate()` uses MERGE semantics: it is idempotent and **re-calling
`relate()` with `edge=EdgeModel(...)` UPDATES the edge properties in place** —
no need for `unrelate()` + `relate()` just to update edge properties.
Pass the class-level descriptor for type safety:

```python
session.relate(user, User.articles, article,
               edge=Authored(at=datetime.now(UTC), primary=True))
# re-calling updates the edge in place — idempotent:
session.relate(user, User.articles, article,
               edge=Authored(at=datetime.now(UTC), primary=False))
session.unrelate(user, User.articles, article)   # remove the relationship
```

**Best practices for relations:**

- **Default to lazy; reach for `fetch=` when you know you need the data**,
  especially in loops (avoids N+1) or before detaching an entity.
- **Async has no lazy loading.** In `AsyncSession`, accessing an unloaded
  relation raises `LazyLoadError` — you *must* use
  `await session.get(Cls, pk, fetch=[...])`. `relate()` / `unrelate()` in async
  are coroutines (`await session.relate(...)`). The session-bound query builder
  is also async: `await session.query(Cls).where(...).all()`. See
  [examples/async_session.py](examples/async_session.py).
- **Detached entities raise `DetachedEntityError`** on lazy access. After the
  session closes or you `expunge()`, the data is gone — fetch eagerly first.
- **Mirror two-sided relationships** by declaring the same `relationship` type
  with `OUTGOING` on one class and `INCOMING` on the other; both views read the
  same edges. Use `direction="BOTH"` for genuinely undirected links.
- **Edge properties** belong on an `Edge` model named to match the `type`; read
  them with `all_with_edges()` (below). Full example:
  [examples/relations.py](examples/relations.py).

---

## Query builder: reading the graph

Build statements with `select(Cls)` (session-independent) and run them through
the session. Filters come from comparing class-level field descriptors.

```python
from runic.ogm import select

# list of entities
users = session.scalars(
    select(User).where(User.active == True).order_by(User.name).limit(20)
)

# one-or-none
alice = session.scalar(select(User).where(User.email == "alice@example.com"))

# count
n = session.count(select(User).where(User.active == True))
```

**Execution methods** (session takes a `select(...)` statement):

| Method | Returns |
|---|---|
| `session.scalars(stmt)` | `list[Entity]` |
| `session.scalar(stmt)` | `Entity \| None` |
| `session.count(stmt)` | `int` |
| `session.all_rows(stmt)` | `list[dict]` — for `project()`, aggregates included |
| `session.all_with_edges(stmt)` | `list[tuple]` — node/edge/node rows |

`session.query(Cls)` returns a session-*bound* builder with terminal methods on
it instead: `.all()`, `.one()`, `.count()`, `.all_rows()`, `.all_with_edges()`.
Both styles are equivalent; `select()` is preferred for composable statements.

**Filtering** — descriptor operators produce filter expressions:

```python
select(Product).where(Product.price > 100)
select(Product).where(Product.name.contains("Graph"))
select(Product).where(Product.sku.is_null())
select(Product).where(Product.id.in_(["p1", "p2"]))
# Boolean composition — parenthesize each operand:
select(Product).where((Product.category == "books") & (Product.active == True))
select(Product).where((Product.a == 1) | (Product.b == 2))
select(Product).where(~(Product.active == True))
```

Operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `.contains()`, `.startswith()`,
`.endswith()`, `.matches()` (regex), `.is_null()`, `.is_not_null()`, `.in_()`,
`.not_in_()`. Multiple `.where()` calls are AND-combined. Refinements:
`.order_by(field, desc=True)`, `.limit(n)`, `.skip(n)`, `.distinct()`.

**Value expressions** — bare fields, handles, `param()`, `when()` and friends
work anywhere Cypher expects a value (WHERE, RETURN, ORDER BY):

```python
from runic.ogm import alias, count, left, param, select, when

# A bare field IS a value and names its own column: RETURN n.id AS id.
# Computed columns get a name with .as_().
select(Message).project(
    Message.id,
    left(Message.body_clean, param("max_chars")).as_("body"),
)

# Compare two properties — no parameter can express this. Handles name the
# variables: alias(Model, "a") makes a.id read a.id in Cypher.
a, b = alias(Address, "a"), alias(Address, "b")
select(a).traverse(a.co_addressed, to=b, edge="r").where(a.id < b.id)

# Conditional aggregation: several counts, one scan, same population
select(Message).project(
    count("*").as_("total"),
    count(when(Message.embedding_model == param("model"), 1)).as_("embedded"),
)
```

Constructors: `Model.f` (bare field), `alias(Model, "m")` → `m.f`,
`param(name)`, `literal(v)`, `fn(name, *args)`, `left()`, `coalesce()`,
`to_lower()`, `to_upper()`, `when(cond, then, else_=…)`, `.as_(name)`,
`col("m", Model.f)` (one-off pin).

**Named parameters** make a statement a reusable constant:

```python
from typing import Final

RECENT: Final = (select(Message).where(Message.id > param("after"))
                 .order_by(Message.id).limit(param("limit")))

rows = session.scalars(RECENT, {"after": cursor, "limit": 500})
RECENT.parameter_names()   # ('after', 'limit')
```

Every execution method takes bindings as a second argument. `limit()`/`skip()`
accept `param()` too. A **missing** parameter raises — it is not silently null,
because a null `$param` matches nothing and looks like an empty database.

**List properties**: use `.any_of(value)` (`$value IN n.refs`), NOT `.in_()`.
On a list property `.in_()` compiles to `n.refs IN $values` and always matches
nothing.

**Projection & aggregation** return rows (dicts), read via `all_rows()`:

```python
from runic.ogm import avg, count, sum_

rows = session.all_rows(select(Product).project(Product.name, Product.price))
# keys are "n.name", "n.price"

summary = session.all_rows(
    select(Order).where(Order.status == "done").project(
        count("*").as_("total"),
        sum_(Order.amount).as_("revenue"),
        avg(Order.amount).as_("avg"),
    )
)
# group by a FIELD — project it alongside the aggregate:
per_city = session.all_rows(
    select(User).project(User.city, count("*").as_("n_users"))
)
# → [{"city": "Berlin", "n_users": 3}, {"city": "Paris", "n_users": 2}, ...]

# group by the whole node — project the handle (handy after a traversal):
u = alias(User, "u")
per_user = session.all_rows(
    select(u).traverse(User.orders, to="o", optional=True).project(
        u, sum_(Order.amount).as_("revenue")
    )
)
```

Cypher has no GROUP BY: every non-aggregated RETURN item is a grouping key, so
`project(key, agg)` *is* the grouped query. Helpers: `count`, `avg`, `sum_`,
`min_`, `max_`, `collect` (each with `.as_()`; `count`/`collect` accept
`distinct=True`). Order by an aggregate by reusing the named expression:
`total = count("*").as_("total")` … `.project(User.city, total)
.order_by(total, desc=True)`.

**Traversal** — alias nodes, hop across relationships, filter by alias:

```python
# Alice's active friends-of-friends who authored a post
f = alias(User, "f")
posts = session.scalars(
    select(User).where(User.id == "alice")
    .traverse(User.friends, to=f)
    .where(f.active == True)
    .traverse(User.authored, to="post")
    .return_target("post")
)
```

- `.traverse(Cls.rel, to="f", edge="e")` — one hop, one call; emits `MATCH`
  (inner join, like Cypher's unmarked case). `optional=True` → `OPTIONAL MATCH`
  (left join; a `WHERE` on it nullifies rows instead of dropping them).
- `to=`/`edge=` take a handle or a string; name only what you reference later.
- **Chaining is a cursor**: each traverse leaves from the variable the previous
  step bound and advances to its own target, so consecutive calls walk a path
  (`(n)-->(f)-->(p)`). Source precedence: `from_=` > the relation's handle
  (`f.authored_posts` leaves from `f`) > the cursor. The bare descriptor only
  supplies the pattern — `.traverse(User.friends, to="f")
  .traverse(User.authored_posts, to="p")` traverses `authored_posts` from
  `f`, not from the root.
- `hops=(1, 3)` on the same call — variable-length path (`*1..3`); `(1, None)`
  unbounded, an int exact. Not combinable with `edge=` (a var-length edge
  binds a list).
- Paging written BEFORE a traverse pages before it (compiles to a `WITH`
  stage); written after, it bounds the final rows. Written order is compiled
  order.
- `.with_("alias")` — explicit pipeline stages. `.return_target("alias")`,
  `.return_nodes(...)`, `.return_edge("e")` — choose result columns.
- Filter on an aliased node or edge with `.where(expr, on="alias")`.

**Edge properties** come back via `all_with_edges()`:

```python
u, r = alias(User, "u"), alias(Rated, "r")
rows = session.all_with_edges(
    select(u).where(u.id == "alice")
    .traverse(User.rated_movies, to="m", edge=r)
    .where(r.score >= 9.0)
    .return_nodes(u, "m").return_edge(r)
)
for user, edge, movie in rows:    # (User, Rated, Movie) tuples
    ...
```

**Search (FalkorDB)** — needs the relevant index created first:

```python
session.fulltext_search(Article, query="graph databases").where(
    Article.published == True
).limit(10).all()

session.vector_search(
    Article, field=Article.embedding, vector=[0.1, 0.2, 0.3, 0.4], k=3
).all()
```

**Inspect without executing:** `cypher, params = select(...).build()`. Reach for
this when debugging a query or explaining what runic generates.

---

**Search and procedures**:

```python
from runic.ogm import col, param, score

# Portable KNN — the dialect picks the backend's procedure
session.all_rows(
    session.vector_search(Message, field=Message.embedding,
                          vector=param("vector"), k=param("k"))
      .where(Message.embedding_model == param("model"))
      .project(Message.id, score().as_("distance"))
      .limit(param("limit")),
    {"vector": v, "k": 200, "model": m, "limit": 20})

# Backend-specific procedure, correlated with the match — one round trip
m = alias(Message, "m")
select(m).call(
    "db.idx.vector.queryNodes", "Message", "embedding",
    param("k"), m.embedding, yields=["node", "score"])
```

- **`k` is NOT `limit`.** `k` is how wide the index search goes; `limit` is what
  the caller sees. A procedure cannot be narrowed before the fact, so every row a
  later `where()` drops must be paid for by `k`. `k == limit` plus a filter gives
  a short page that looks like a small database.
- **`score()` means opposite things.** Vector = distance (lower is closer,
  normalised across backends); fulltext = relevance (higher is better). Never
  sort both into one list.
- **A row with no vector is absent from the index**, not ranked low, and nothing
  says so. Report coverage with any semantic answer.
- **`call()` is not portable** — it names a procedure literally. Use
  `vector_search()`/`fulltext_search()` unless you need a specific backend's.
- `var("name")` references a procedure yield or a `WITH` binding.

**Index DDL** is not a query: use `IndexOperations` (`runic.ogm.schema.runtime_index`),
not the builder. Vector-index dimension follows the configured embedder, which is
a setting a migration cannot express. A wrong-length vector is stored and
silently never indexed — read `describe()` first, and clear stored vectors when
the dimension changes.

**Writes in bulk** — `unwind()` for many rows in one statement; `set()`,
`delete()` and `returning()` chain onto a `select()` too:

```python
from runic.ogm import count, encode_rows, param, row, select, unwind

# Upsert nodes. Only the KEY goes in merge(); everything else in set(),
# or a changed value makes MERGE miss the node and create a second.
MERGE_GROUPS = (unwind(param("rows"))
    .merge(Group, key={Group.id: row("id")}, alias="g")
    .set({Group.size: row("size")}, on="g"))

# Attach edges: MATCH both endpoints (not merge - a missing endpoint is a
# caller bug), then merge between them.
MERGE_ABOUT = (unwind(param("rows"))
    .match(Message, key={Message.id: row("message_id")}, alias="m")
    .match(Topic, key={Topic.id: row("topic_id")}, alias="t")
    .merge_edge("m", "ABOUT", "t", alias="r", edge_model=About)
    .set({About.score: row("score")}, on="r"))

# Batched delete; loop until removed == 0
DELETE_GROUPS = (select(Group).with_("n", limit=param("batch"))
    .delete(detach=True).returning(count("n").as_("removed")))

session.all_rows(MERGE_GROUPS, {"rows": encode_rows(Group, payload)})
```

Rules that bite:
- **`detach=True` for nodes, NEVER for an edge.** Detaching an edge deletes both
  endpoints — real data destroyed to clean up a derived edge. Use `.delete("r")`.
- **`encode_rows(Model, rows)` before binding `$rows`.** Values inside `$rows`
  skip the mapper, so a `datetime` reaches the driver unencodable.
- **A write emits no `RETURN` unless you call `returning()`.** That is deliberate.
- **`directed=False`** on `merge_edge` for symmetric edges — rejected by FalkorDB,
  which needs the caller to order the pair canonically instead.
- Prefer `MERGE` over `session.add()` (a `CREATE`) whenever a job may re-run:
  derived labels carry no unique constraint to stop a duplicate.

**Page before you expand** — paging written before a traversal compiles into a
`WITH` stage that bounds the rows entering it:

```python
m, r = alias(Message, "m"), alias(Address, "r")
(select(m)
   .where(m.id > param("after"))
   .order_by(m.id).limit(param("limit"))          # page cut HERE
   .traverse(Message.sent_to, to=r, optional=True)
   .project(m.id, collect(r.id, distinct=True).as_("addressed")))
```

The same calls written after the traversal bound the final rows instead — the
written order is the compiled order. A trailing `.limit()` on this query would
expand the whole graph and then discard all but one page. `with_(..., where=...)`
is Cypher's `HAVING` — the only way to filter an aggregated value. **Always
order when you limit**: paging without an order is undefined and two runs can
return different pages.

**Fan-out**: `traverse(rel, from_=m)` anchors to a named variable instead of
continuing the cursor's chain, so several traversals can leave the same node —
without it, the second of two traversals leaves from the first one's target.
(A handle's own attribute also names its source: `traverse(a.co_addressed,
...)` leaves from `a` whatever the cursor says.)

**Alternation**: `traverse(rel, types=["SENT_TO", "COPIED_TO"])` emits
`[:SENT_TO|COPIED_TO]`. Use it when the relationship *is* the walk over both —
two separate patterns double-count anything matching both. Not available on
Apache AGE.

**Direction override**: `traverse(rel, direction="OUTGOING")` on a `BOTH`
relation. When both ends share a label, an arrow matches each edge once; without
one it matches from each end, so a count doubles.

**Backend gaps are refused, not emitted.** runic raises `NotImplementedError`
naming the construct and backend rather than sending Cypher the backend rejects.
Absent: alternation (AGE), undirected `MERGE` (FalkorDB), `CALL … YIELD`
(ArcadeDB, AGE), fulltext (ArcadeDB, AGE), vector (AGE).

## Sessions & repositories

- **Lifecycle:** use `with Session(driver) as session:`. `add()` / `add_all()`
  stage inserts; `delete()` stages removals. `flush()` writes pending changes
  without ending the logical transaction; `commit()` flushes then clears
  tracking; `rollback()` discards pending state.
  Setting any attribute on a loaded entity marks it dirty for the next commit.
- **Identity map:** within one session, `get()` returns the same instance for a
  given `(type, pk)`. `rollback()` discards pending state; `expire()`/`refresh()`
  re-read from the graph; `expunge()` detaches.
- **Repository** wraps a session + model for collection reads:
  `Repository(session, User).find_all(skip=0, limit=50)`, `.find_all_by_ids(ids)`,
  `.count()`, `.exists(pk)`. Pagination is offset-based via `skip`/`limit` (there
  is no `Page` object).
- **Custom repositories** subclass `Repository[T]` and add methods using
  `self.query()` (the bound builder) or the raw-Cypher helpers:
  - `self.cypher(q, params, returns=Cls)` — maps rows to entities
  - `self.cypher(q, params, returns=int)` — maps to a scalar; `write=True` for mutations
  - `self.cypher_one(q, params, returns=int)` — first mapped row; use for single scalars
  - `self.cypher_raw(q, params)` — returns `GraphResult` with `.columns` (list of names) and `.rows` (list of value lists)

```python
class ArticleRepository(Repository[Article]):
    def by_author(self, author: str) -> list[Article]:
        return self.cypher(
            "MATCH (a:Article {author: $a}) RETURN a", {"a": author}, returns=Article
        )

    def count_by_status(self, status: str) -> int:
        return self.cypher_one(
            "MATCH (a:Article {status: $s}) RETURN count(a)", {"s": status}, returns=int
        )

    def stats(self):
        raw = self.cypher_raw(
            "MATCH (a:Article) RETURN a.author AS author, count(a) AS n", {}
        )
        return [dict(zip(raw.columns, row)) for row in raw.rows]
```

See [references/api-reference.md](references/api-reference.md) for every method
signature and [references/cookbook.md](references/cookbook.md) for async,
multi-backend, performance, and error-handling recipes.

---

## Key rules

- Prefer `relate()`/`unrelate()` and the query builder over raw Cypher; drop to
  `session.execute()` / `repo.cypher()` only for what the builder can't express.
  Column aliases, scalar functions, `CASE`, property-to-property comparison and
  named parameters are all builder features now — don't reach for a string.
- **Type checkers do not see descriptor methods.** `Model.field` is typed by its
  annotation, so `.is_null()`, `.in_()`, `.any_of()` and `&`/`|` between
  comparisons need a suppression comment on the line under `ty`:
  ```python
  .where(Message.id.is_not_null() & (Message.id != ""))  # ty: ignore[unresolved-attribute, unsupported-operator]
  ```
  Write the code normally and add the comment; do not restructure to avoid it.
- Use `fetch=[...]` to avoid N+1 in loops and **always** in async code.
- `optional=False` whenever you filter on a traversed edge's properties.
- `Vector`, `GeoLocation`, and `interned` are **FalkorDB-only** native types;
  on other backends the raw value is stored. **Fulltext and vector search also
  work on Neo4j and Memgraph** but require pre-created named indexes (see
  cookbook multi-backend table); they are absent on ArcadeDB and Apache AGE.
- **Multi-backend driver params differ.** FalkorDB uses `graph=` (the graph
  name); Neo4j/Memgraph/ArcadeDB use `database=`, `username=`, `password=`.
  Neo4j defaults to `encrypted=True`. Example:
  ```python
  create_driver("neo4j", host="localhost", port=7687,
                database="neo4j", username="neo4j", password="…")  # encrypted=True
  ```
  Pass the driver to `Session(driver)` — models and queries are unchanged.
- Indexes are *declared* on models but *created* by `runic.migrate` — keep
  schema changes in migrations, not application code.
