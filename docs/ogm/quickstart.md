# Quickstart

`runic.ogm` maps Python classes to graph nodes and edges.  You define
a model, open a `Session`, and call methods —
the OGM generates Cypher, executes it, and hands back typed Python objects.

The example below uses FalkorDB.  Swap the `create_driver` arguments for any
other supported backend — see [drivers](./drivers.md) and [installation](./installation.md).

---

## Installation

```bash
uv add "runic-py[falkordb]"   # or: pip install "runic-py[falkordb]"
```

Start a local FalkorDB instance for this example:

```bash
docker run -p 6379:6379 falkordb/falkordb
```

---

## Define a model

Every graph entity inherits from `Node`.
Declare properties with `Field()`.
The `labels` keyword controls which graph labels are applied:

```python
from runic.ogm import Field, Node, Repository, Session, create_driver

class Language(Node, labels=["Language"]):
    id: str = Field(primary_key=True)
    title: str = Field()
    code: str = Field(unique=True)
```

Every model must have exactly one primary-key field.  runic uses it to
build `MATCH (n:Language {id: $id})` predicates and to key the session's
identity map.

::: info See also
[concepts](./concepts.md) — Node, Edge, Field, Relation, object states, and dirty tracking
:::

---

## Connect

Pass a `GraphDriver` to `Session`.  The driver
holds the connection; the session holds the unit of work.  Create the driver
once per application process and share it across sessions:

```python
driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
```

See [drivers](./drivers.md) for the full set of supported backends and their kwargs.

---

## Create

Add entities to the session and call `commit()`.  The OGM emits a
`CREATE` statement for each new entity on `flush()`, which happens
automatically when you call `commit()`:

```python
with Session(driver) as session:
    lang = Language(id="en", title="English", code="en")
    session.add(lang)
    session.commit()
    # lang is now Persistent — id, title, code are readable
```

Entities created outside a session are *transient*.  They become *pending*
after `session.add()` and *persistent* after the first successful flush.

---

## Read

Use a `Repository` for collection
reads, or `session.get()` for a single lookup by primary key:

```python
with Session(driver) as session:
    repo = Repository(session, Language)
    all_langs: list[Language] = repo.find_all()
    english: Language | None = session.get(Language, "en")
```

`session.get()` returns `None` if the key does not exist.  Within the
same session, calling `session.get(Language, "en")` a second time returns
the *same Python object* (identity map — no extra Cypher).

---

## Update

Mutate a field on a persistent entity.  The descriptor sets `_dirty = True`;
`commit()` emits a `MERGE … SET` for all dirty fields:

```python
with Session(driver) as session:
    en: Language | None = session.get(Language, "en")
    assert en is not None
    en.title = "English (UK)"      # marks _dirty = True
    session.commit()               # emits MERGE (n:Language {id: $id}) SET n.title = $title
```

Only the mutated fields are included in the `SET` clause — the OGM does
not overwrite fields it did not touch.

---

## Delete

Mark an entity for deletion with `session.delete()`; the `DETACH DELETE`
runs on `flush()`:

```python
with Session(driver) as session:
    en: Language | None = session.get(Language, "en")
    assert en is not None
    session.delete(en)
    session.commit()
```

---

## Query builder

For filtered, ordered, or paginated reads use `select()`
to build a composable statement and execute it via the session:

```python
from runic.ogm import select

stmt = (
    select(Language)
    .where(Language.code == "en")
    .order_by(Language.title)
)
with Session(driver) as session:
    results: list[Language] = session.scalars(stmt)
```

The builder is lazy — nothing is sent to the database until you pass the
statement to a session execution method such as `session.scalars()`,
`session.scalar()`, or `session.count()`.

::: info
The legacy `session.query(Language).where(...).all()` pattern is still
fully supported; `select()` is preferred because it lets you build the
statement outside the session scope (e.g. across multiple `if` branches)
before executing it once.
:::

::: info See also
[query_builder](./query-builder.md) — full query-builder reference with Cypher output
:::

---

## Next steps

::: info See also
- [examples/orm/01_simple_crud.py](https://github.com/jenreh/runic/blob/main/examples/orm/01_simple_crud.py) — End-to-end runnable example: create, read, update, delete, and basic query-builder usage.
- [concepts](./concepts.md) — object states, dirty tracking, identity map, type converters
- [relationships](./relationships.md) — lazy loading, eager loading, `relate()` / `unrelate()`, edge properties
- [session](./session.md) — unit-of-work lifecycle, flush, commit, rollback, raw execute
- [api](../api.md) — full API reference
:::
