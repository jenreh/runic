# Define your models

This page shows how to declare graph models in `runic.ogm`: nodes, edges,
fields with indexes and constraints, and relationships.

Models are plain Python dataclasses — no database logic in the class itself.
All state (dirty tracking, identity caching, query execution) lives in the
`Session`.

---

## Declare nodes and edges

Every graph entity inherits from either `Node`
or `Edge`.

```python
from runic.ogm import Edge, Field, Node

class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True, generated=True)
    name: str
    email: str = Field(index=True, unique=True)

class InvitationEdge(Edge, type="INVITED_TO"):
    role: str
    status: str
    invited_at: str
```

`Node` maps to a graph vertex.  `Edge` maps to a relationship type.
Both register themselves in the global metadata registry when the class body
executes — forward references in `target=` strings are resolved at that point.

**labels** controls which graph labels are applied.  Multi-label nodes
implement polymorphic hierarchies:

```python
class Location(Node, labels=["Location"], primary_label="Location"):
    id: str
    title: str

class Country(Location, labels=["Location", "Country"], primary_label="Location"):
    iso_code: str = Field(unique=True)
```

**primary_label** (optional) is the label used in `MATCH` predicates when
the node has more than one label.  When it is omitted, the first entry in
`labels` is used.  Set it on both the parent and the subclass so that
`MATCH (n:Location)` matches all subtypes:

```python
# MATCH (n:Location {id: $id}) — both Country and City are matched
location: Location | None = session.get(Location, "FR")
```

::: info See also
[examples/orm/01_simple_crud.py](https://github.com/jenreh/runic/blob/main/examples/orm/01_simple_crud.py)
— Defines a `Node` with `Field` descriptors and walks through all object states.

[examples/orm/02_polymorphic_locations.py](https://github.com/jenreh/runic/blob/main/examples/orm/02_polymorphic_locations.py)
— Multi-label hierarchy (`Location → Country, City`), `primary_label`, and polymorphic repository queries.
:::

---

## Add fields and relationships

Properties and relationships are declared with separate functions to keep
scalar data and graph topology clearly separated:

* `Field()` — scalar properties, index hints, and constraints.
* `Relation()` — graph relationships (edges).

Both return `FieldDescriptor` typed as
`Any`, so `name: str = Field()` is accepted by type checkers without
error.  At runtime the descriptor intercepts `__set__` to set `_dirty`
and `__get__` to trigger lazy loading.

**Field parameters**

| Parameter | Type | Description |
| --- | --- | --- |
| `default` | `Any` | Python default value (evaluated lazily via `default_factory` for mutable types) |
| `index` | `bool` | Create a `RANGE` index |
| `index_type` | `str` | `"FULLTEXT"` or `"VECTOR"` |
| `unique` | `bool` | Unique constraint |
| `required` | `bool` | Validated on save; raises `FieldValidationError` |
| `converter` | `TypeConverter` | Custom encode/decode; omit for `datetime`, `Enum`, `Vector`, and `GeoLocation` — converters are assigned automatically |
| `generated` | `bool` | The database assigns the node ID on `CREATE` |
| `interned` | `bool` | Store via `intern()` for deduplication of repeated strings (country names, tags, status codes, etc.) — FalkorDB only |

**Relation parameters**

| Parameter | Type | Description |
| --- | --- | --- |
| `relationship` | `str` | Edge-type string (required) |
| `direction` | `str` | `"OUTGOING"`, `"INCOMING"`, or `"BOTH"` (required) |
| `target` | `str \| type` | Entity class (or forward-reference string) for the other end (required) |
| `edge_model` | `str \| type` | Optional `Edge` subclass holding edge properties |
| `lazy` | `bool` | Delay relationship loading (default `True`) |
| `cascade` | `bool` | Auto-add related entities when the owning entity is added to a session |
| `default` | `Any` | Default value (defaults to `None`) |

---

## Understand object states

Each entity lives in exactly one state at any time, mirroring SQLAlchemy's
unit-of-work pattern.  The session is the source of truth for state
transitions:

| State | When the object enters it |
| --- | --- |
| **Transient** | Created with `Entity(...)`, not yet known to any session |
| **Pending** | After `session.add(entity)`; written on `flush()` |
| **Persistent** | Loaded from the graph, or after the first successful `flush()` |
| **Deleted** | After `session.delete(entity)`; `DETACH DELETE`d on `flush()` |
| **Detached** | After `session.expunge(entity)` or `session.close()` |

A transient entity that is never added to a session is never persisted.  If you
construct an entity with `Entity(id="x", ...)` and discard it, no query runs.

---

## How dirty tracking works

Two private flags drive which Cypher statement the mapper emits:

* `_new` — `True` until the first successful flush.
  The mapper emits `CREATE` when this is true.
* `_dirty` — `True` when any field is written on a persistent entity.
  The mapper emits `MERGE … SET` when this is true.

The descriptor `__set__` sets `_dirty = True` automatically.  The session
clears both flags after a successful `flush()`.

Only the fields that were actually set are included in the `SET` clause.
The OGM does not write fields that haven't changed:

```python
with Session(driver) as session:
    person = session.get(Person, "alice")
    assert person is not None
    person.name = "Alice Smith"
    # _dirty = True, only 'name' will be in SET
    session.commit()
    # emits: MERGE (n:Person {id: $id}) SET n.name = $name
```

---

## How the identity map avoids duplicate queries

The session keeps one Python instance per `(EntityClass, primary_key)` pair.
Two reads for the same primary key within the same session return the *same*
object — no second Cypher query:

```python
with Session(driver) as session:
    a: Person | None = session.get(Person, "alice")
    b: Person | None = session.get(Person, "alice")
    assert a is b   # True — single object, no second query
```

Repository reads also register entities in the identity map.  If you call
`repo.find_all()` and then `session.get(Person, "alice")` in the same
session, the result is the same object that was returned by `find_all()`.

The identity map is cleared when the session is closed.  Objects become
*detached* and no longer track dirty state.

---

## Use native Python types

The OGM assigns converters *automatically* for well-known annotation types —
no `converter=` argument needed:

| Annotation type | Converter assigned automatically |
| --- | --- |
| `datetime` | `DatetimeConverter` — stores as ISO-8601 string |
| `Enum` subclass | `EnumConverter` — stores `.value` |
| `Vector` | `VectorConverter` — stores via `vecf32()` |
| `GeoLocation` | `GeoLocationConverter` — stores via `point()` |

```python
from datetime import datetime
from enum import StrEnum
from runic.ogm import Field, GeoLocation, Node, Vector

class Status(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"

class Place(Node, labels=["Place"]):
    id: str
    status: Status                         # EnumConverter auto-assigned
    created_at: datetime                   # DatetimeConverter auto-assigned
    embedding: Vector = Field(index_type="VECTOR")  # VectorConverter
    location: GeoLocation                  # GeoLocationConverter
```

An explicit `converter=` always takes precedence over auto-assignment.

**Interned strings** *(FalkorDB only)*

Use `interned=True` to store a string property via FalkorDB's `intern()`
function, which deduplicates the value across the database.  Useful for
high-cardinality-but-low-variety fields like country names or status codes:

```python
class Person(Node, labels=["Person"]):
    id: str = Field()
    country: str = Field(interned=True)
```

**Custom converters**

Implement `TypeConverter` (`to_graph` /
`from_graph`) for any type not covered above.  Set `cypher_fn` on the
converter class to wrap the Cypher parameter with a backend function:

```python
from runic.ogm import TypeConverter

class MyConverter(TypeConverter):
    cypher_fn = "myFunc"   # wraps Cypher parameter: myFunc($value)

    def to_graph(self, value): ...
    def from_graph(self, value): ...
```

::: info See also
[examples/orm/06_native_types.py](https://github.com/jenreh/runic/blob/main/examples/orm/06_native_types.py)
— `Vector`, `GeoLocation`, interned strings, `datetime` and `Enum` auto-converters in action.
:::

---

## How model discovery works

All `Node` and `Edge` subclasses are registered automatically in the
global `metadata` singleton when the class is
defined.  The registry is used by `IndexManager`
to discover index hints and by the mapper for polymorphic label resolution.

Forward references in `target=` strings are resolved at import time.

```python
from runic.ogm import metadata

for node_meta in metadata.all_nodes():
    print(node_meta.cls.__name__, node_meta.labels)
```
