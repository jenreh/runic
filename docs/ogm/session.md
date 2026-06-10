# Read and write data

The `Session` is the unit-of-work manager
for Cypher-based graph databases. It owns all mutations, manages the identity
map, and controls the flush/commit lifecycle. For async code, see
[./async.md](./async.md) — `AsyncSession` mirrors this API with `await`.

::: info See also
[examples/orm/01_simple_crud.py](https://github.com/jenreh/runic/blob/main/examples/orm/01_simple_crud.py)
Session lifecycle, mutations, flush, commit, and rollback in a single runnable file.

[examples/orm/04_pagination_and_custom_queries.py](https://github.com/jenreh/runic/blob/main/examples/orm/04_pagination_and_custom_queries.py)
`session.execute()` for raw write queries; custom repository methods; offset pagination.
:::

## Opening a session

`Session` accepts a `GraphDriver` (or
`AsyncGraphDriver` for the async variant).
Use the helpers in `runic.ogm.driver` to build one:

```python
from runic.ogm import Session, create_driver

# FalkorDB
driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
with Session(driver) as session:
    ...   # commit on success, rollback on exception

# ArcadeDB (via Bolt)
driver = create_driver(
    "arcadedb",
    host="localhost", port=7687, database="mydb",
    username="root", password="playwithdata",
)
with Session(driver) as session:
    ...
```

## Mutations

All writes go through the Session, never the Repository.

```python
from runic.ogm import Session

with Session(driver) as session:
    # add: transient → pending; CREATE on flush
    session.add(entity)
    session.add_all([e1, e2])

    # update: set any field → _dirty = True; MERGE SET on flush
    entity.name = "New Name"

    # delete: persistent → deleted; DETACH DELETE on flush
    session.delete(entity)

    session.commit()    # flush + clear pending/deleted sets
```

## Single-entity lookup

`session.get()` checks the identity map first, then queries the graph.
Returns `None` if not found.

```python
person = session.get(Person, "alice")
person_with_rels = session.get(Person, "alice", fetch=["company"])
```

## Flush and commit

```python
session.flush()     # execute writes; does not clear identity map
session.commit()    # flush + clear pending/deleted sets
```

### Transaction model

Each `flush()` sends each pending entity as its own query. Entities
with `generated=True` IDs must be flushed individually so the returned
ID can be assigned before the next write.

`rollback()` discards the **un-flushed** pending/deleted sets only. Once
`flush()` has executed queries, those writes are permanent.

## Rollback

```python
session = Session(driver)
try:
    session.add(Person(id="bob", name="Bob", email="bob@example.com"))
    session.rollback()   # discard pending; nothing written to graph
finally:
    session.close()
```

The context manager calls `rollback()` automatically on exception.

## Expire and refresh

```python
session.expire(entity)   # clear cached attrs; reloaded on next access
session.refresh(entity)  # immediate re-query from graph
```

## Expunge

```python
session.expunge(entity)   # remove from session → detached; no DB action
session.expunge_all()
```

## Composable statement execution

`select()` creates a
`QueryBuilder` that is **not bound to a
session**. Build the statement freely — including conditional filters — then
pass it to one of the session execution methods:

```python
from runic.ogm import select

stmt = select(Person).where(Person.active == True)
if min_age > 0:
    stmt = stmt.where(Person.age >= min_age)

# All five execution methods accept a QueryBuilder
people: list[Person]  = session.scalars(stmt)
person: Person | None = session.scalar(stmt)
n:      int           = session.count(stmt)
rows:   list[dict]    = session.all_rows(stmt)

# Async sessions accept the same stmt
people = await async_session.scalars(stmt)
```

The same `stmt` object is **reusable** — execute it multiple times, against
different sessions if needed. Each execution restores the session binding to
`None` afterwards.

| Method | Returns |
| --- | --- |
| `scalars(stmt)` | `list[T]` — decoded node entities; `T` inferred from `QueryBuilder[T]` |
| `scalar(stmt)` | `T \| None` — first entity, or `None` if the result set is empty |
| `count(stmt)` | `int` — total matching nodes |
| `all_rows(stmt)` | `list[dict[str, Any]]` — raw column-value dicts |
| `all_with_edges(stmt)` | `list[tuple[Any, ...]]` — tuples of `(node, edge, node)` |

::: tip
`session.query(Person).where(...).all()` is still fully supported.
Prefer `select()` when you need to compose the query across multiple
code paths before executing.
:::

## Raw Cypher

For the common cases prefer the [query builder](./query-builder.md).
`session.execute()` is the escape hatch for write mutations and Cypher
features not covered by the builder.

```python
from runic.ogm import select

# Prefer select() + session.scalars() for reads
stmt = (
    select(Person)
    .where(Person.id == "alice")
    .alias("p")
    .traverse(Person.knows).alias("f")
)
friends: list[Person] = session.scalars(stmt)

# Write mutations (SET, REMOVE, …) require session.execute(write=True)
session.execute(
    "MATCH (t:Trip {status: $old}) SET t.status = $new",
    {"old": "draft", "new": "archived"},
    write=True,
)
```

## Session API summary

| Method | Description |
| --- | --- |
| `add(entity)` | Transient/detached → pending |
| `add_all([entities])` | Batch `add` |
| `delete(entity)` | Persistent → deleted; `DETACH DELETE` on flush |
| `get(EntityClass, pk, fetch=[])` | Identity map check → graph query; `None` if not found |
| `flush()` | Execute pending/dirty/deleted sets; clear `_dirty` |
| `commit()` | `flush()` + clear pending/deleted sets |
| `rollback()` | Discard un-flushed pending/deleted sets; expire persistent entities |
| `expire(entity)` | Invalidate attribute cache; reloaded on next access |
| `refresh(entity)` | Immediate re-query from graph |
| `expunge(entity)` | Remove from session (→ detached); no graph action |
| `expunge_all()` | Expunge all tracked entities |
| `scalars(stmt)` | Execute a `select()` statement; return `list[T]` |
| `scalar(stmt)` | Execute a statement; return first `T` or `None` |
| `count(stmt)` | Execute a statement; return row count as `int` |
| `all_rows(stmt)` | Execute a statement; return `list[dict[str, Any]]` |
| `all_with_edges(stmt)` | Execute a statement; return `list[tuple[Any, ...]]` |
| `execute(cypher, params, write)` | Raw Cypher; returns `GraphResult` (`.rows`, `.columns`) |
| `close()` | `expunge_all()` + release connection |

## Session best practices

**Keep sessions short.** Open a session for one logical operation and close
it when done — don't hold sessions across long-running computations or
between HTTP requests.

**Always use the context manager.** It commits on success and rolls back on
exception automatically:

```python
with Session(driver) as session:
    session.add_all([a, b, c])
    session.commit()
```

**Commit in one place.** Call `commit()` once at the end of a unit of work.
Multiple commits in a single session create multiple logical transactions;
prefer staging all changes then committing once.

**Reuse the driver, not the session.** Create the driver once at startup and
close it on shutdown. Create a new `Session` for each request or operation.

## Avoiding N+1

Lazy relationships fire one query per access. In a loop that is an N+1:

```python
# BAD — one query for users, then one per user for articles
for user in session.scalars(select(User)):
    print(len(user.articles))   # lazy load each iteration
```

Use `fetch=` on `session.get()` to eager-load one entity's relations in a
single query:

```python
# GOOD for a single entity
user = session.get(User, "alice", fetch=["articles"])
for article in user.articles:   # already loaded
    print(article.title)
```

For a *collection* of parents, use a traversal query instead of a loop of
`get()` calls:

```python
# GOOD for a collection — single round-trip
from runic.ogm import select

stmt = (
    select(User).alias("u")
    .traverse(User.articles, edge_alias="e").alias("a")
    .return_nodes("u", "a")
)
rows = session.all_with_edges(stmt)
```

Async sessions have no lazy loading at all — the rule applies unconditionally.
See [./async.md](./async.md) for async-specific patterns.

## Connection management

`ConnectionManager` and
`AsyncConnectionManager` wrap a
FalkorDB graph handle for reuse across sessions:

```python
from runic.ogm import ConnectionManager

manager = ConnectionManager(graph)
with manager.session() as session:
    ...
```

::: info See also
[./async.md](./async.md) — full async session guide including `AsyncConnectionManager`
:::
