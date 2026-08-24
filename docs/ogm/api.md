# OGM API Reference

> **Note:** This is a manually-maintained API reference. For the authoritative API, read the [source on GitHub](https://github.com/jenreh/runic/tree/main/src/runic).

`runic.ogm` is a lightweight graph OGM for Cypher-based graph databases.
It follows a SQLAlchemy-style architecture: driver → session → mapper →
repository. FalkorDB, Neo4j, Memgraph, ArcadeDB and Apache AGE are supported
via the `GraphDriver` / `GraphDialect` abstractions.

Everything on this page is importable from the package root:

```python
from runic.ogm import Node, Edge, Field, Relation, Session, select, alias, param
```

---

## How the pieces fit together

runic separates *what you declare*, *what builds Cypher*, and *what talks to a
database*. Each layer only knows the one below it.

<img class="diagram" src="/diagrams/runic-ogm-architecture.svg" alt="runic.ogm architecture: models and metadata feed statements, executed by the session through the mapper, driver and dialect onto five backends">

<!-- Source: docs/diagrams/runic-ogm-architecture.drawio — regenerate with docs/diagrams/regenerate.sh -->

`Repository` sits beside the session as a typed read helper for one model.
`IndexManager` / `SchemaManager` (from `runic.migrate`) live outside the read
path and manage index DDL.

### Which class do I actually touch?

| Task | Use |
|------|-----|
| Declare a model | `Node`, `Edge`, `Field()`, `Relation()` |
| Connect | `create_driver()` or a backend factory |
| Read / write one entity | `Session.get()`, `session.add()`, `session.commit()` |
| Build a query | `select()` + `QueryBuilder`, executed via `session.scalars()` |
| Search | `fulltext_search()`, `vector_search()` |
| Bulk write | `unwind()` + `MutationBuilder` |
| Relationships | `session.relate()` / `session.unrelate()`, `.traverse()` |
| Typed reads for one model | `Repository` |
| Indexes | `IndexSpec`, `IndexManager`, `SchemaManager` |

`Mapper`, `RelationshipLoader`, `RelationshipWriter`, `MetaData` and the
dialects are wired for you — documented here because they are public, and
because reading them is how you extend runic to a new backend.

---

## runic.ogm.core — Models & Fields

### Node

`runic.ogm.core.models.Node`

Base class for graph node models. Subclass it with the `labels` and optional
`primary_label` class keywords; `__init__` is generated from the declared
`Field()` descriptors.

```python
class Location(Node, labels=["Location"]):
    id: str = Field(primary_key=True)
    name: str = Field()

class Country(Location, labels=["Location", "Country"], primary_label="Location"):
    iso_code: str = Field(unique=True)
```

**Class keywords**

- `labels` — the label list written to the graph; defaults to `[cls.__name__]`
- `primary_label` — the label used in `MATCH` predicates; defaults to `labels[0]`

Nodes are plain data objects — they carry no persistence methods of their own.
Writes go through the `Session` (`session.add()`, `session.delete()`,
`session.commit()`).

**What `__init_subclass__` does**, in order: synthesise a `Field()` for every
bare annotation (`name: str` with no `= Field(...)`), collect `_fields`, assign
the automatic converters (`datetime`, `Enum`, `Vector`, `GeoLocation`), and
generate `__init__` from the result. That is why a plain annotation and an
explicit `Field()` behave identically.

Class attributes set by `__init_subclass__` (internal, but visible when
debugging): `_labels`, `_primary_label`, `_fields`. Instances carry `_new` and
`_dirty` lifecycle flags that the `Mapper` reads on flush.

### Edge

`runic.ogm.core.models.Edge`

Base class for graph edge property models. Subclass it with the `type` class
keyword; it defaults to the class name.

```python
class InvitationEdge(Edge, type="INVITED_TO"):
    role: str = Field(required=True)
```

An `Edge` instance holds only the relationship's *properties* — the endpoints
are supplied at write time (`session.relate(src, rel, tgt, edge=...)`) and
returned by `all_with_edges()`. Class attribute `_edge_type` records the type;
instances carry the same `_new` / `_dirty` flags as `Node`.

### Field

`runic.ogm.core.descriptors.Field`

Factory function that declares a node or edge property field. Returns a
`FieldDescriptor` typed as `Any`, so `name: str = Field()` type-checks.
All arguments are keyword-only.

```python
class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    age: int | None = Field(default=None)
    email: str = Field(index=True, unique=True)
    country: str = Field(interned=True)
```

| Argument | Default | Meaning |
|----------|---------|---------|
| `default` | `MISSING` | Default value; mutually exclusive with `default_factory` |
| `default_factory` | `None` | Zero-arg callable producing the default |
| `init` | `True` | Include the field in the generated `__init__` |
| `kw_only` | `True` | Keyword-only in the generated `__init__` |
| `index` | `False` | Declare a `RANGE` index on the property |
| `index_type` | `None` | `"FULLTEXT"` or `"VECTOR"` |
| `unique` | `False` | Declare a `UNIQUE` constraint (implies a backing index) |
| `required` | `False` | Reject `None` on assignment |
| `primary_key` | `False` | The identity used by `session.get()` and the identity map |
| `converter` | `None` | Explicit `TypeConverter`; usually assigned automatically |
| `generated` | `False` | The database assigns the value (server-generated id) |
| `interned` | `False` | Write through FalkorDB's `intern()` to deduplicate repeated strings |

A field with both `unique=True` and `index=True` emits only the `UNIQUE` spec.

### Relation

`runic.ogm.core.descriptors.Relation`

Factory function that declares a relationship attribute on a node. Returns a
`FieldDescriptor` configured as a relation. All arguments are keyword-only.

```python
class Person(Node, labels=["Person"]):
    company: "Company | None" = Relation(
        relationship="WORKS_FOR",
        direction="OUTGOING",
        target="Company",
    )
    friends: list["Person"] = Relation(
        relationship="FRIEND_OF",
        direction="OUTGOING",
        target="Person",
    )
```

| Argument | Default | Meaning |
|----------|---------|---------|
| `relationship` | *required* | Cypher relationship type; validated as an identifier |
| `direction` | *required* | `"OUTGOING"` / `"INCOMING"` / `"BOTH"` |
| `target` | *required* | Target node class, or its name as a string (needed for self-references and forward references) |
| `edge_model` | `None` | `Edge` subclass carrying the relationship's properties |
| `cascade` | `False` | Cascade deletes to the related nodes |
| `lazy` | `True` | Load on first attribute access rather than eagerly |
| `default` | `None` | Value before the relation is loaded |
| `default_factory` | `None` | Zero-arg callable producing the default |
| `init` | `True` | Include in the generated `__init__` |

A relation field cannot also declare `index` or `unique` — both raise
`ValueError`.

### FieldDescriptor

`runic.ogm.core.descriptors.FieldDescriptor`

Descriptor class that backs `Field()` and `Relation()` declarations. It is a
*data* descriptor: values live in the instance `__dict__`, and writing through
it sets `instance._dirty = True`, which is how the `Mapper` detects changes.

Accessed at the **class** level it returns *itself*, which is what makes
`User.name == "Alice"` a query expression rather than a boolean.

- `name` / `field_name` — name of the field on the model class
- `owner` — the model class that declares it
- every argument passed to `Field()` / `Relation()` is kept as an attribute of
  the same name (`default`, `converter`, `index`, `index_type`, `unique`,
  `primary_key`, `relationship`, `direction`, `target`, `edge_model`,
  `interned`, `generated`, `lazy`, `cascade`, …)
- `has_default()` / `get_default()` — default-value access used by the
  generated `__init__`

**Comparison operators** (each returns a `FilterExpr`):
`==`, `!=`, `>`, `>=`, `<`, `<=`

**Expression helpers**: `contains()`, `startswith()`, `endswith()`,
`matches()`, `in_()`, `not_in_()`, `any_of()`, `is_null()`, `is_not_null()`,
`as_()`

```python
select(User).where(User.name == "Alice")
select(User).where(User.bio.contains("graph"))
select(User).where(User.deleted_at.is_null())
select(User).where(User.role.in_(["admin", "owner"]))
```

`any_of()` is the reversed form — `Tag.name.any_of(User.tags)` compiles to
`$p0 IN n.tags`-style membership with the operands the other way round.

### FieldInfo

`runic.ogm.core.descriptors.FieldInfo`

Pairs a field name with its `FieldDescriptor`; built while the generated
`__init__` is assembled.

- `name` — the field name on the model class
- `field` — the backing `FieldDescriptor` (where `default`, `converter`,
  `relationship`, … live)
- `is_collection` — `True` when the annotation is a `list[...]`

For a relation, the relationship type and target live on the descriptor:
`fi.field.relationship`, `fi.field.direction`, `fi.field.target`,
`fi.field.edge_model`.

### MISSING

`runic.ogm.core.descriptors.MISSING`

Falsy sentinel meaning "no default was declared". Distinguishes
`Field()` from `Field(default=None)` — the first makes the argument required in
the generated `__init__`, the second gives it `None`.

### _NOT_LOADED

`runic.ogm.core.descriptors._NOT_LOADED`

Falsy sentinel stored in a lazy relation field. Reading a field that holds it
triggers `Session.load_relationship()`. `session.relate()` and
`session.unrelate()` write it back after a change so the next access re-fetches
from the graph.

---

## runic.ogm.core — MetaData

### MetaData

`runic.ogm.core.metadata.MetaData`

Registry that tracks all `Node` and `Edge` model classes. Subclassing a model
registers it automatically; you rarely call these yourself.

- `register_node(cls)` / `register_edge(cls)` — register a model class
- `all_nodes()` → `list[NodeMeta]` / `all_edges()` → `list[EdgeMeta]`
- `get_node_meta(cls)` / `get_edge_meta(cls)` — look up by class
- `resolve_node_by_label(label)` / `resolve_edge_by_type(edge_type)` — look up by
  graph label or relationship type; this is how the `Mapper` decodes a raw graph
  node back into the right Python class
- `resolve_target(target)` — resolve a `Relation(target=...)` string or class
- `snapshot()` / `restore(snap)` / `clear()` — registry state, useful in tests

### NodeMeta

`runic.ogm.core.metadata.NodeMeta`

Metadata record for a registered node class.

- `cls` — the Python class
- `labels` — the declared label list
- `primary_label` — the label used in `MATCH` predicates
- `fields` — `list[FieldInfo]`
- `pk_field_name` — name of the primary-key field, or `None`

### EdgeMeta

`runic.ogm.core.metadata.EdgeMeta`

Metadata record for a registered edge class.

- `cls` — the Python class
- `edge_type` — relationship type string
- `fields` — `list[FieldInfo]`

### metadata

`runic.ogm.core.metadata.metadata`

The global `MetaData` singleton instance that models register into.

### get_metadata

`runic.ogm.core.metadata.get_metadata`

Module-level function that returns the global `MetaData` singleton — the same
object as `metadata`.

---

## runic.ogm.core — Type Converters

### TypeConverter

`runic.ogm.core.types.TypeConverter`

Protocol for field type converters. Pass one as `Field(converter=...)`;
runic assigns the built-ins automatically for `datetime`, `Enum`, `Vector` and
`GeoLocation` fields.

- `to_graph(value)` — convert a Python value to its graph representation
- `from_graph(value)` — convert a graph value back to Python
- `cypher_fn` — name of a Cypher function to wrap the value in on write
  (`None` for most converters)

### DatetimeConverter

`runic.ogm.core.types.DatetimeConverter`

Converter for `datetime` fields. Serialises to ISO-8601 strings and deserialises back to `datetime` objects.

- `to_graph(value)` — returns an ISO-8601 string
- `from_graph(value)` — returns a `datetime`

### EnumConverter

`runic.ogm.core.types.EnumConverter`

Converter for `Enum` fields. Serialises to the enum value and deserialises back to the enum member.

- `to_graph(value)` — returns `value.value`
- `from_graph(value)` — returns `EnumClass(value)`

### Vector

`runic.ogm.core.types.Vector`

Native type for vector (embedding) fields — a `list[float]` subclass, so it
behaves as a plain list everywhere else.

```python
class Article(Node, labels=["Article"]):
    embedding: Vector | None = Field(default=None, index_type="VECTOR")
```

The index dimension is not carried on the type; pass it when the index is
created (`IndexManager`, or a migration `op.create_vector_index`).

### VectorConverter

`runic.ogm.core.types.VectorConverter`

Converter that serialises `Vector` instances to lists and back. Assigned
automatically to `Vector`-annotated fields.

- `to_graph(value)` — returns `list[float]`
- `from_graph(value)` — returns a `Vector`
- `cypher_fn` — `"vecf32"`

### GeoLocation

`runic.ogm.core.types.GeoLocation`

Native type for geographic coordinate fields — a frozen dataclass.

- `latitude` — `float`
- `longitude` — `float`

### GeoLocationConverter

`runic.ogm.core.types.GeoLocationConverter`

Converter that serialises `GeoLocation` instances to dicts and back. Assigned
automatically to `GeoLocation`-annotated fields.

- `to_graph(value)` — returns `{"latitude": ..., "longitude": ...}`
- `from_graph(value)` — returns a `GeoLocation`
- `cypher_fn` — `"point"`

---

## runic.ogm.driver — Protocols

These are the contracts every backend implements. A new backend is a driver
plus a dialect; nothing above this layer changes.

### GraphDriver

`runic.ogm.driver.GraphDriver`

Protocol for a synchronous driver.

- `dialect` — property; the `GraphDialect` for this backend
- `execute(cypher, params)` → `GraphResult`
- `close()` — release the connection

### AsyncGraphDriver

`runic.ogm.driver.AsyncGraphDriver`

Protocol for an asynchronous driver. Same surface, with `execute()` and
`close()` as coroutines.

### TransactionalGraphDriver

`runic.ogm.driver.TransactionalGraphDriver`

Runtime-checkable protocol for drivers that support explicit ACID
transactions — `BoltDriver` (Neo4j, Memgraph, ArcadeDB) and `AGEDriver`.
`FalkorDBDriver` deliberately does **not** implement it: each `GRAPH.QUERY` is
individually atomic.

- `begin()` — open a transaction; raises `RuntimeError` if one is already active
- `commit()` — commit the active transaction; no-op when none is active
- `rollback()` — discard all changes since `begin()`; no-op when none is active

`Session` detects support with `isinstance(driver, TransactionalGraphDriver)`
and wires its own `commit()` / `rollback()` accordingly.

### GraphDialect

`runic.ogm.driver.GraphDialect`

Protocol for the strategy object the builder and mapper consult for every
backend-specific Cypher fragment.

- `unsupported_features` — `frozenset[str]` of `CypherFeature` names this
  backend cannot parse; empty for most backends
- `generated_id_where(alias, param)` — the `WHERE id(n) = $p` form
- `cypher_fn_for_field(fi)` — the write-side wrapping function (`vecf32`,
  `point`, `intern`, …), or `None`
- `fulltext_call(label, alias, query_param)` — the `CALL … YIELD` clause that
  opens a fulltext query
- `vector_knn_start(alias, labels_str, type_name, field_name)` — the
  `MATCH`/`CALL` clause that opens a KNN query
- `vector_knn_score_expr(alias, field_name)` — the score expression appended to
  `RETURN`
- `wrap_node(raw)` / `wrap_edge(raw)` — normalise raw driver objects into
  `GraphNode` / `GraphEdge`

Concrete dialects additionally expose `vector_knn_call()`,
`vector_score_expr()` and `fulltext_yields_score`.

### GraphResult

`runic.ogm.driver.GraphResult`

Protocol for a normalised query result — what every `execute()` returns.

- `rows` — `list[list[Any]]`, positional cell values
- `columns` — `list[str]`, the column names

### GraphNode

`runic.ogm.driver.GraphNode`

Protocol for a normalised node in a result.

- `element_id` — the backend's internal identifier
- `labels` — `list[str]`
- `properties` — `dict[str, Any]`

### GraphEdge

`runic.ogm.driver.GraphEdge`

Protocol for a normalised relationship in a result.

- `type` — relationship type string
- `properties` — `dict[str, Any]`

### CypherFeature

`runic.ogm.driver.CypherFeature`

Names of Cypher constructs whose support varies by backend. Naming them lets
the builder refuse to emit unparseable Cypher — and say which construct and
which backend — before the query is sent, instead of surfacing a driver syntax
error pointing at a character.

| Constant | Construct | Missing on |
|----------|-----------|------------|
| `RELATIONSHIP_ALTERNATION` | `[:A\|B]` | Apache AGE |
| `UNDIRECTED_MERGE` | `MERGE (a)-[r:T]-(b)` | FalkorDB |
| `PROCEDURE_CALL` | `CALL … YIELD` | ArcadeDB, Apache AGE |
| `FULLTEXT_SEARCH` | fulltext index from Cypher | ArcadeDB, Apache AGE |
| `VECTOR_SEARCH` | vector index from Cypher | Apache AGE |

### dialect_supports

`runic.ogm.driver.dialect_supports`

`dialect_supports(dialect, feature)` → `bool`. Dialects declare only their
gaps, so a backend that says nothing is taken to support the construct.
Returns `True` when *dialect* is `None`.

### require_feature

`runic.ogm.driver.require_feature`

`require_feature(dialect, feature, construct)` — raises `NotImplementedError`
naming both the backend and the construct when unsupported; returns silently
otherwise.

### yield_as

`runic.ogm.driver.yield_as`

`yield_as(yielded, alias)` → one `YIELD` item, omitting a no-op rename.
`YIELD node AS node` is rejected by at least FalkorDB with a message that
points nowhere near the cause.

---

## runic.ogm.driver — Drivers & Dialects

| Backend | Driver | Dialect | Factory | Transactions |
|---------|--------|---------|---------|--------------|
| FalkorDB | `FalkorDBDriver` / `AsyncFalkorDBDriver` | `FalkorDBDialect` | `create_falkordb_driver` | per-query only |
| Neo4j | `BoltDriver` | `Neo4jDialect` | `create_neo4j_driver` | full ACID |
| Memgraph | `BoltDriver` | `MemgraphDialect` | `create_memgraph_driver` | full ACID |
| ArcadeDB | `BoltDriver` | `ArcadeDBDialect` | `create_arcadedb_driver` | full ACID |
| Apache AGE | `AGEDriver` | `AGEDialect` | `create_age_driver` | full PostgreSQL ACID |

### FalkorDBDriver

`runic.ogm.driver.falkordb.FalkorDBDriver`

Synchronous driver for FalkorDB.

- `dialect` — property; a `FalkorDBDialect`
- `falkordb_connection` — property; the underlying `(client, graph)` pair
- `execute(query, params)` — run a Cypher query and return a `GraphResult`
- `close()` — release the connection

### AsyncFalkorDBDriver

`runic.ogm.driver.falkordb.AsyncFalkorDBDriver`

Asynchronous driver for FalkorDB. Requires `falkordb.asyncio.FalkorDB`.

- `dialect` — property; a `FalkorDBDialect`
- `execute(query, params)` — coroutine; run a Cypher query and return a `GraphResult`
- `close()` — coroutine; release the connection

### FalkorDBDialect

`runic.ogm.driver.falkordb.FalkorDBDialect`

Cypher dialect customisations for FalkorDB.

- `unsupported_features` — `{UNDIRECTED_MERGE}`
- `cypher_fn_for_field(fi)` — `vecf32` for `Vector`, `point` for `GeoLocation`,
  `intern` for `interned=True` fields
- fulltext via `CALL db.idx.fulltext.queryNodes()`; `fulltext_yields_score` is
  `True`
- vector KNN via the HNSW index procedure; `vector_score_expr()` is normalised
  so lower is closer

### BoltDriver

`runic.ogm.driver.bolt.BoltDriver`

Generic Bolt-protocol driver; used for Neo4j, Memgraph and the ArcadeDB Bolt
endpoint. Implements `TransactionalGraphDriver`.

- `dialect` — property; the dialect it was constructed with
- `execute(query, params)` — run a Cypher query and return a `GraphResult`
- `begin()` / `commit()` / `rollback()` — explicit transaction control
- `close()` — release the connection

### Neo4jDialect

`runic.ogm.driver.neo4j.Neo4jDialect`

Cypher dialect customisations for Neo4j. `unsupported_features` is empty.

- fulltext via `CALL db.index.fulltext.queryNodes(indexName, query)` — requires
  a pre-created index named after the label
- vector KNN via `CALL db.index.vector.queryNodes(indexName, k, vec)` —
  requires an index named `{type}_{field}`
- integer node ids via `id()`, no `toInteger()` cast
- no Cypher function wrappers (`vecf32`, `intern`) — raw values only; `point`
  is still used for `GeoLocation`
- TLS via `bolt+s://` (`encrypted=True` on the factory)

### MemgraphDialect

`runic.ogm.driver.memgraph.MemgraphDialect`

Cypher dialect customisations for Memgraph. `unsupported_features` is empty.

- fulltext via `CALL text_search.search_all(indexName, query)` — requires the
  built-in / MAGE `text_search` module and an index created as
  `CREATE TEXT INDEX {label} ON :{label}`
- vector KNN via `CALL vector_search.search(indexName, k, vec)`, yielding
  `node`, `distance` and `similarity`; the index must be pre-created with
  `CREATE VECTOR INDEX {type}_{field} ON :{type}({field}) WITH CONFIG {...}`
- integer node ids via `id()`, no `toInteger()` cast
- no Cypher function wrappers except `point`
- TLS via `bolt+s://` (`encrypted=True` on the factory)

### ArcadeDBDialect

`runic.ogm.driver.arcadedb.ArcadeDBDialect`

Cypher dialect customisations for ArcadeDB.

- `unsupported_features` — `{PROCEDURE_CALL, FULLTEXT_SEARCH}`;
  `fulltext_call()` raises `NotImplementedError`
- `supports_geo_update` — `False`
- `cypher_fn_for_field()` returns `None` for every field — raw values only

### AGEDriver

`runic.ogm.driver.age.AGEDriver`

Driver for Apache AGE (PostgreSQL graph extension), over psycopg3. Implements
`TransactionalGraphDriver`; the `ag_catalog.cypher(...)` SQL wrapping happens
here, not in the dialect.

- `dialect` — property; an `AGEDialect`
- `execute(query, params)` — run a Cypher query via AGE and return a `GraphResult`
- `begin()` / `commit()` / `rollback()` — map onto the psycopg3 connection
- `close()` — release the connection

### AGEDialect

`runic.ogm.driver.age.AGEDialect`

Cypher dialect customisations for Apache AGE, plus the multi-label emulation
AGE needs because it stores one label per node.

- `unsupported_features` — `{RELATIONSHIP_ALTERNATION, PROCEDURE_CALL,
  FULLTEXT_SEARCH, VECTOR_SEARCH}`
- `needs_labels_property` — `True`; extra labels are kept in a `_labels`
  property
- `labels_clause(labels)` / `subtype_where(alias, labels)` — emit the single
  label and the `_labels` predicate that recovers the rest
- `fulltext_call()` and `vector_knn_start()` raise `NotImplementedError`

### create_driver

`runic.ogm.driver.factory.create_driver`

`create_driver(backend, **kwargs)` → `GraphDriver`. Generic factory; *backend*
is `"falkordb"`, `"arcadedb"`, `"neo4j"`, `"memgraph"` or `"age"`, and the
keyword arguments are forwarded to that backend's constructor. Raises
`ValueError` on an unknown backend.

```python
driver = create_driver("falkordb", host="localhost", port=6379, graph="my_graph")

driver = create_driver(
    "neo4j", host="localhost", port=7687, database="neo4j",
    username="neo4j", password="secret", encrypted=True,
)
```

### create_falkordb_driver

`runic.ogm.driver.falkordb.create_falkordb_driver`

Creates a `FalkorDBDriver`, or an `AsyncFalkorDBDriver` when asked for the
async variant.

### create_neo4j_driver

`runic.ogm.driver.neo4j.create_neo4j_driver`

Creates a `BoltDriver` configured with `Neo4jDialect`.

### create_memgraph_driver

`runic.ogm.driver.memgraph.create_memgraph_driver`

Creates a `BoltDriver` configured with `MemgraphDialect`.

### create_arcadedb_driver

`runic.ogm.driver.arcadedb.create_arcadedb_driver`

Creates a `BoltDriver` configured with `ArcadeDBDialect`.

### create_age_driver

`runic.ogm.driver.age.create_age_driver`

Creates an `AGEDriver` from PostgreSQL connection parameters.

---

## runic.ogm.mapper — Model ⇄ Cypher

The mapper is the only layer that knows both the model metadata and the
dialect. The session owns one and delegates every encode/decode step to it;
you construct one directly only when building Cypher outside a session.

### Mapper

`runic.ogm.mapper.mapper.Mapper`

`Mapper(meta, dialect=None)` — translates model instances into Cypher and raw
graph results back into model instances.

**Query construction** (each returns `(cypher, params)`)

- `build_create_query(entity)` — `CREATE` for a new node
- `build_update_query(entity)` — `SET` for a dirty node
- `build_delete_query(entity)` — `DETACH DELETE`
- `build_get_query(cls, pk)` — single-node lookup by primary key
- `build_find_all_query(cls, skip=0, limit=None)`
- `build_find_all_by_ids_query(cls, pks)`
- `build_count_query(cls)` / `build_exists_query(cls, pk)`

**Decoding**

- `decode_node(raw_node, hint_cls=None)` — a raw driver node → a model
  instance; without a hint the class is resolved from the labels via `MetaData`
- `decode_edge(raw_edge, hint_cls=None)` — the same for relationships
- `update_entity_from_node(entity, raw_node)` — refresh an existing instance
  in place, which is what keeps the identity map coherent

**Metadata & dialect access**

- `meta` — property; the `MetaData` in use
- `dialect` — property; the `GraphDialect` in use
- `labels_clause(labels)` / `subtype_where(alias, labels)` — delegate to the
  dialect's multi-label handling
- `require_node_meta(cls)` — `NodeMeta` or raise `MetadataError`
- `get_pk_value(entity)` / `get_pk_field_name(cls)` / `is_generated_pk(cls)`

### RelationshipLoader

`runic.ogm.mapper.relationship_loader.RelationshipLoader`

`RelationshipLoader(meta, mapper)` — builds the `OPTIONAL MATCH` Cypher behind
lazy attribute access and the `fetch=[...]` eager-loading argument, and decodes
the results.

- `build_lazy_load_query(entity, fi)` — the query behind a first attribute read
- `decode_lazy_result(result, fi)` — decode it into an entity or list
- `build_get_with_fetch_query(cls, pk, fetch)` — one query for a node plus the
  named relations
- `build_find_all_with_fetch_query(cls, fetch, skip, limit)`
- `build_find_all_by_ids_with_fetch_query(cls, pks, fetch)`
- `decode_eager_columns(result, cls, fetch)` — split the collected columns back
  onto the entities

### RelationshipWriter

`runic.ogm.mapper.relationship_writer.RelationshipWriter`

`RelationshipWriter(meta, mapper)` — builds the Cypher behind
`Session.relate()` and `Session.unrelate()`.

- `build_relate_query(source, fi, target, edge=None)` — `MERGE` semantics: an
  existing relationship has its edge properties updated, a missing one is
  created
- `build_unrelate_query(source, fi, target)` — delete the relationship

---

## runic.ogm.session — Session

### Session

`runic.ogm.session.session.Session`

`Session(driver, mapper=None, *, log_cypher=False)` — synchronous unit of work.
Owns all mutations, the identity map, and the flush/commit lifecycle.

```python
with Session(driver) as session:
    session.add(User(id="u1", name="Alice"))
    session.commit()
```

> **Security:** `log_cypher=True` emits every query *and its bound parameters*
> at DEBUG level. Parameters carry raw property values, which may include PII
> or secrets — use it for local debugging only.

**Staging and lifecycle**

- `add(entity)` — stage a node or edge for insertion
- `add_all(entities)` — stage a list of them
- `delete(entity)` — stage a node or edge for deletion
- `flush()` — write staged changes to the database
- `commit()` — flush and finalise the transaction
- `rollback()` — discard staged changes (and, on a transactional driver, the
  driver transaction)
- `close()` — expunge tracked entities; rolls back an orphaned transaction so
  the connection is released cleanly
- `__enter__` / `__exit__` — context manager; commits on clean exit, rolls back
  on an exception

**Reading**

- `get(cls, pk, fetch=None)` — identity-map hit, or a query; `None` when absent.
  `fetch=["rel", ...]` eager-loads those relations in the same query with
  `OPTIONAL MATCH`
- `refresh(entity)` — re-query and update the instance in place
- `load_relationship(entity, field_name)` — load a lazy relation and cache it
  on the entity; normally triggered by attribute access, not called directly

**Relationships**

- `relate(source, field_name, target, edge=None)` — `MERGE` the relationship;
  pass an `Edge` instance to write its properties. *field_name* may be a string
  or the class-level descriptor (`User.invited_trips`)
- `unrelate(source, field_name, target)` — delete the relationship

Both invalidate the cached relation value on *source*, so the next read
re-fetches.

**Executing statements** — each takes an unbound builder from `select()`,
`vector_search()`, `fulltext_search()` or `unwind()`, plus optional `params`

- `scalars(stmt, params=None)` → `list[T]` — decoded entities; type-safe
- `scalar(stmt, params=None)` → `T | None` — first entity; adds `LIMIT 1`
  internally without mutating the statement
- `all_rows(stmt, params=None)` → `list[dict[str, Any]]` — column-keyed rows
- `all_with_edges(stmt, params=None)` → `list[tuple]` — `(NodeA, Edge, NodeB)`
  tuples; the statement needs `return_nodes()` and `return_edge()`
- `count(stmt, params=None)` → `int`
- `execute(cypher, params=None, write=False)` — raw Cypher; returns the driver
  result with no entity mapping

**Builder entry points** (session-bound; terminals execute immediately)

- `query(cls, name=None)` → `QueryBuilder`
- `fulltext_search(cls, *, query, fields=None)` → `FulltextQueryBuilder`
- `vector_search(cls, *, field, vector, k=10)` → `VectorQueryBuilder`

**Identity map**

- `register_or_get(entity)` — return the tracked instance for this identity
- `decode_and_register_node(raw_node, cls)` — decode and track in one step
- `expire(entity)` — mark stale; the next read re-queries
- `expunge(entity)` / `expunge_all()` — stop tracking
- `mapper` / `rel_loader` — properties exposing the wired collaborators

**Transaction model** — determined by the injected driver:

| Driver | Behaviour |
|--------|-----------|
| FalkorDB | No multi-query transactions. Each `GRAPH.QUERY` is atomic. `commit()` flushes; `rollback()` discards *un-flushed* state only — it cannot undo writes already sent. |
| Bolt (Neo4j, Memgraph, ArcadeDB) | Full ACID. The first query lazily opens a Bolt transaction; `commit()` / `rollback()` apply or discard it as a unit. |
| Apache AGE | Full PostgreSQL ACID. psycopg3 opens an implicit `BEGIN`; `commit()` / `rollback()` map to the connection's. |

### AsyncSession

`runic.ogm.session.async_session.AsyncSession`

`AsyncSession(driver, mapper=None, *, log_cypher=False)` — asynchronous
counterpart to `Session`, with the same method names and the same transaction
model.

```python
async with AsyncSession(driver) as session:
    user = await session.get(User, "u1")
    await session.commit()
```

Coroutines: `get()`, `flush()`, `commit()`, `rollback()`, `refresh()`,
`relate()`, `unrelate()`, `execute()`, `scalars()`, `scalar()`, `all_rows()`,
`all_with_edges()`, `count()`, `close()`, `__aenter__` / `__aexit__`.

Sync: `add()`, `add_all()`, `delete()`, `query()`, `fulltext_search()`,
`vector_search()` and the identity-map methods — they only stage or construct.
`query()` returns an `AsyncQueryBuilder` whose terminals are awaited.

`load_relationship()` raises `LazyLoadError` — a coroutine cannot be awaited
from `__get__`, so implicit lazy loading has no async form. Reading an unloaded
relation attribute on an async-loaded entity therefore raises. Use
`await session.get(cls, pk, fetch=["rel"])` or an explicit `traverse()`.

### ConnectionManager

`runic.ogm.session.connection_pool.ConnectionManager`

`ConnectionManager(db, graph_name)` — holds a FalkorDB client and a graph name,
and hands out drivers for it. A `Session` is built from the driver, not from the
manager.

- `acquire()` — return a `FalkorDBDriver` for the configured graph
- `release(driver)` — return a driver to the manager (currently a no-op)
- `graph_name` — the configured graph name

### AsyncConnectionManager

`runic.ogm.session.connection_pool.AsyncConnectionManager`

`AsyncConnectionManager(db, graph_name)` — the same, over an async FalkorDB
client (`falkordb.asyncio.FalkorDB`).

- `acquire()` — **sync**; return an `AsyncFalkorDBDriver` for the configured graph
- `release(driver)` — coroutine; return a driver to the manager (currently a no-op)
- `graph_name` — the configured graph name

---

## runic.ogm.repository — Repository

### Repository

`runic.ogm.repository.repository.Repository`

`Repository(session, cls)` — a read helper for a single `Node` or `Edge` model.
Writes stay on the session (`session.add()`, `session.delete()`), and a
single-entity lookup is `session.get(cls, pk)`.

- `find_all(fetch=None, skip=0, limit=None)` — all entities of this type
- `find_all_by_ids(pks, fetch=None)` — batch lookup by primary key
- `count()` — number of entities of this type
- `exists(pk)` — `True` when a node with that primary key exists
- `query(name=None)` — a session-bound `QueryBuilder`; `name` sets the root variable
- `cypher(query, params=None, *, returns=None, write=False)` — raw Cypher,
  decoded into `returns` instances when given
- `cypher_one(...)` — the same, returning the first row or `None`
- `cypher_raw(...)` — the same, returning the undecoded driver result

`fetch=[...]` on the two `find_*` methods eager-loads the named relations in
the same query.

### AsyncRepository

`runic.ogm.repository.async_repository.AsyncRepository`

Asynchronous counterpart to `Repository`, with the same method names. Every
method that touches the database is a coroutine; `query(name=None)` is sync and
returns an `AsyncQueryBuilder` whose terminals are awaited.

---

## runic.ogm.query — Statement factories

The four entry points below return **unbound** builders: composable, reusable,
and executed through a session. The session-bound equivalents on `Session` and
`Repository` execute on their own terminals instead.

### select

`runic.ogm.query.select`

`select(cls, name=None)` → `QueryBuilder`. *cls* is a registered `Node`
subclass or an `alias()` handle; *name* is the root Cypher variable (default
`n`) and is rejected when *cls* is already a handle.

```python
stmt = select(Person).where(Person.age > 30).limit(10)   # MATCH (n:Person)
stmt = select(Person, "p").where(Person.age > 30)        # MATCH (p:Person)

p = alias(Person, "p")
stmt = select(p).where(p.age > param("min_age"))         # MATCH (p:Person)

people = session.scalars(stmt, {"min_age": 30})
```

Calling a terminal like `.all()` on an unbound statement raises `RuntimeError`
— execute it through the session.

### vector_search

`runic.ogm.query.vector_search`

`vector_search(field, *, vector, k=10)` → `VectorQueryBuilder`. *field* is a
`Vector` field descriptor (`Message.embedding`) or a handle's attribute
(`node.embedding`) — the descriptor knows its owner, so the class is not
repeated. Passing anything else raises `TypeError`.

```python
KNN = (
    vector_search(Message.embedding, vector=param("vector"), k=param("k"))
    .where(Message.embedding_model == param("model"))
    .project(Message.id, score().as_("distance"))
    .limit(param("limit"))
)
rows = session.all_rows(KNN, {"vector": vec, "k": 200, "model": "v3", "limit": 20})
```

### fulltext_search

`runic.ogm.query.fulltext_search`

`fulltext_search(cls, *, query, fields=None)` → `FulltextQueryBuilder`. The
label needs a fulltext index. *fields* is informational — the procedure uses
whichever index it finds for the label.

```python
SEARCH = (
    fulltext_search(Message, query=param("text"))
    .project(Message.id, score().as_("relevance"))
    .order_by(score().as_("relevance"), desc=True)
    .limit(param("limit"))
)
```

### unwind

`runic.ogm.query.mutation.unwind`

`unwind(source, *, as_="row")` → `MutationBuilder`. Opens a bulk write over a
list parameter.

```python
unwind(param("rows")).merge(Group, key=Group.id).set(Group.name).returning(Group.id)
```

---

## runic.ogm.query — Builders

### QueryBuilder

`runic.ogm.query.builder.QueryBuilder`

Fluent query builder. All non-terminal methods return `self`.

**Filtering and shaping**

- `where(expr, on=None)` — add a predicate; repeated calls are AND-combined
- `order_by(field, *, desc=False)` — a descriptor, a named `.as_()` expression, or `"name DESC"`
- `limit(n)` / `skip(n)` — accept an integer or `param("name")`; written before a
  traversal or a write they compile into a `WITH` stage (positional paging)
- `distinct()` — `RETURN DISTINCT`
- `project(*values)` — the RETURN line: fields, handles, expressions, aggregates;
  bare fields auto-name their columns, mixing values and aggregates groups
- `return_target(alias)` / `return_nodes(*aliases)` / `return_edge(alias)`

**Traversal**

`traverse(relation_field, *, to=None, edge=None, optional=False, from_=None, types=None, direction=None, hops=None)`

One call is one Cypher pattern. `.traverse(User.rated, to=m, edge=r)` emits
`MATCH (u)-[r:RATED]->(m)`; `hops=(1, 5)` makes it `[:RATED*1..5]` (mutually
exclusive with `edge=`). Name the target with `to=` whenever anything later
references it; naming the edge with `edge=` is what enables edge-property
filters and `all_with_edges()`.

`with_(*vars, order_by=, desc=, limit=, skip=, where=, distinct=)` — repeatable
`WITH` stage.

**Procedures and writes**

- `call(procedure, *args, yields=())` — invoke a procedure, optionally correlated
- `set(*assignments, on=None)` — mappings and/or bare descriptors (which read the same-named `$rows` key); `None` clears
- `delete(*variables, detach=False)` — defaults to the current target
- `returning(*values)` — what a write reports; without it a write returns nothing

**Terminals** (each takes an optional `params` mapping)

| Terminal | Returns |
|----------|---------|
| `all()` | `list[T]` — decoded entities |
| `one()` | `T \| None` |
| `count()` | `int` |
| `scalar()` | the first cell of the first row |
| `scalars()` | the first column of every row, as a flat list |
| `all_rows()` | `list[dict[str, Any]]` — column-keyed |
| `all_with_edges()` | `list[tuple]` — `(NodeA, Edge, NodeB)` |

> **`scalar` / `scalars` mean different things here than on the session.**
> The builder's versions return *cells* and require a single-column statement;
> `Session.scalar()` / `Session.scalars()` return *decoded entities* and require
> a node-shaped one. `all()` is the builder terminal that matches
> `session.scalars()`.

**Compilation** (no database contact)

- `build()` → `(cypher, params)`
- `parameter_names()` → the declared parameter names, sorted
- `bind(params)` → merged bindings; raises on a missing declared parameter

### AsyncQueryBuilder

`runic.ogm.query.specialised.AsyncQueryBuilder`

Asynchronous counterpart to `QueryBuilder`. Only the terminals differ — `all()`,
`one()`, `count()`, `scalar()`, `scalars()`, `all_rows()` and
`all_with_edges()` are coroutines. The generated Cypher is identical.

### FulltextQueryBuilder

`runic.ogm.query.specialised.FulltextQueryBuilder`

Built by `fulltext_search()` or `Session.fulltext_search()`. Opens with the
backend's fulltext procedure; everything after behaves as on any other builder.

The match score is available as `score()` — a **relevance**, higher being
better. Not available on ArcadeDB or Apache AGE.

### VectorQueryBuilder

`runic.ogm.query.specialised.VectorQueryBuilder`

Built by `vector_search()` or `Session.vector_search()`. Opens with the
backend's vector index procedure.

`k` is the index search width; `limit` is how many rows the caller sees. They are
separate because a procedure cannot be narrowed before the fact — a following
`where()` discards rows `k` already paid for.

`score()` is a **distance**, normalised so lower is closer on every backend. Not
available on Apache AGE.

### MutationBuilder

`runic.ogm.query.mutation.MutationBuilder`

Built by `unwind()`. A `QueryBuilder` subclass whose root is an `UNWIND`.

- `merge(cls, key=..., alias=None)` — upsert a node on its key; `key=Cls.id` reads the same-named row key
- `match(cls, key=..., alias=None)` — bind an existing node
- `merge_edge(source, relationship, target, alias=None, edge_model=None, directed=True)` — *relationship* may be an `Edge` class, a `Relation` field, or a type string

`set()`, `returning()`, `build()` and the terminals come from `QueryBuilder`.
On FalkorDB, `directed=False` raises — undirected `MERGE` is unsupported there.

---

## runic.ogm.query — Value expressions

Anything that renders to a Cypher *value* is a `ValueExpr`. Bare field
descriptors count too, which is why `project(User.name)` and
`project(to_lower(User.name))` compose the same way.

| Constructor | Emits |
|-------------|-------|
| `Model.field` (bare) | `n.field` — fields are values |
| `alias(Model, "m")` / `m.field` | `m` / `m.field` — a named variable handle |
| `col("m", Model.field)` | `m.field` — one-off pin |
| `param("name")` | `$name` — declared, bound by the caller |
| `var("name")` | a bare Cypher variable (a procedure yield, a `WITH` binding) |
| `score()` | the score a search procedure yielded |
| `literal(value)` | `$pN` — an inlined value, still parameterised |
| `fn("name", *args)` | an arbitrary function call |
| `left(value, length)`, `coalesce(*values)`, `to_lower(value)`, `to_upper(value)` | the named function calls |
| `when(cond, then, *pairs, else_=None)` | `CASE WHEN … END` |
| `row("key", var="row")` | `row.key` — a field of the current `UNWIND` row |
| `expr.as_("name")` | `expr AS name` |
| `encode_rows(Model, rows)` | field converters applied across a `$rows` payload |

Each constructor is documented under the class it returns: `alias()` → `Alias`,
`param()` → `ParamRef`, `literal()` → `LiteralValue`, `row()` → `RowRef`,
`fn()` / `left()` / `coalesce()` / `to_lower()` / `to_upper()` → `FnCall`,
`when()` → `CaseExpr`, `.as_()` → `AliasedExpr`, and `col()` / `var()` /
`score()` → `PropertyRef`.

### ValueExpr

`runic.ogm.query.values.ValueExpr`

Base class for every value expression. Carries the same comparison operators
and helpers as `FieldDescriptor` — `==`, `!=`, `>`, `>=`, `<`, `<=`,
`is_null()`, `is_not_null()`, `contains()`, `startswith()`, `endswith()`,
`matches()`, `in_()`, `not_in_()`, `any_of()` — plus:

- `as_(name)` → `AliasedExpr`
- `to_cypher(compiler)` — render (internal)
- `referenced_aliases(compiler)` — which variables this expression needs in
  scope, used to validate `WITH` stages

### Alias

`runic.ogm.query.values.Alias`

A named variable handle, created by `alias(cls, name)`. Attribute access on it
returns a `PropertyRef`, so the handle both *is* a value (`m` in `RETURN m`) and
produces values (`m.field`).

```python
m = alias(Message, "m")
select(m).where(m.sent_at > param("since")).project(m.id, m.subject)
```

Passing a handle to `select()` / `traverse(to=...)` / `return_nodes()` is what
lets later calls reference the same variable without repeating the string.

### PropertyRef

`runic.ogm.query.values.PropertyRef`

A property access on a variable — `m.field`. Produced by `Alias.__getattr__`,
`col()` and `var()`.

- `alias` — the Cypher variable
- `prop` — the property name
- `owner` — the model class, when known

### ParamRef

`runic.ogm.query.values.ParamRef`

A declared query parameter — `$name`, produced by `param()`. The name is
validated as an identifier. `QueryBuilder.parameter_names()` collects these, and
`bind()` raises when one is left unbound.

### LiteralValue

`runic.ogm.query.values.LiteralValue`

A Python value inlined into the statement, produced by `literal()`. Rendered as
an auto-numbered parameter (`$p0`, `$p1`, …) rather than interpolated — literals
never reach the Cypher string.

### RowRef

`runic.ogm.query.values.RowRef`

A key of the current `UNWIND` row — `row.key`, produced by `row()`. The variable
name defaults to `row` and matches `unwind(..., as_=...)`.

### FnCall

`runic.ogm.query.values.FnCall`

A Cypher function call, produced by `fn()` and by the named helpers
(`left`, `coalesce`, `to_lower`, `to_upper`). The function name is validated as
an identifier; arguments may be any value expression.

### CaseExpr

`runic.ogm.query.values.CaseExpr`

A `CASE WHEN … THEN … ELSE … END`, produced by `when()`.

```python
project(
    when(User.age >= 18, literal("adult"), else_=literal("minor")).as_("bracket")
)
```

### AliasedExpr

`runic.ogm.query.values.AliasedExpr`

An expression with an `AS` name, produced by `.as_()`.

- `result_name` — the column name the row dict will use

Pass the same `AliasedExpr` to `order_by()` to sort by a computed column
without repeating the expression.

### col

`runic.ogm.query.values.col`

`col(field, on)` → `PropertyRef` — pin one field to a named variable without
creating a handle. Both argument orders work: `col(User.name, "u")` and
`col("name", User.name)`.

### encode_rows

`runic.ogm.query.values.encode_rows`

`encode_rows(Model, rows)` — apply *Model*'s field converters across a list of
dicts before it is bound as the `$rows` payload of an `unwind()` write. Without
it, `datetime`, `Enum`, `Vector` and `GeoLocation` values reach the driver
unconverted.

---

## runic.ogm.query — Expression types

These are what `where()` consumes. You rarely construct them directly — the
descriptor operators produce them.

### Expr

`runic.ogm.query.expressions.Expr`

Abstract base class for all query expression types.

### FilterExpr

`runic.ogm.query.expressions.FilterExpr`

A single `WHERE` predicate — `alias.prop OP $pN`. Produced by the descriptor
operator overloads.

- `cls` — the model class that owns the field
- `prop` — the property name
- `op` — comparison operator string (`"="`, `">"`, `"<"`, …)
- `value` — the comparison value (or the right-hand field, for a
  field-to-field comparison)
- `alias` — explicit Cypher variable, when the expression is pinned to a handle
- `negate` / `left` / `reverse` — modifiers set by `~`, by a pinned left-hand
  side, and by reversed operands (`any_of()`)

### CompoundExpr

`runic.ogm.query.expressions.CompoundExpr`

Combines expressions with `AND` or `OR` — produced by `&` and `|`.

- `op` — `"AND"` or `"OR"`
- `operands` — `list[Expr]`

```python
select(User).where((User.active == True) & (User.age >= 18))
```

### NegatedExpr

`runic.ogm.query.expressions.NegatedExpr`

Wraps an expression with `NOT` — produced by `~`.

- `operand` — the `Expr` to negate

### OrderExpr

`runic.ogm.query.expressions.OrderExpr`

Represents a single `ORDER BY` term, produced by `order_by()`.

- `alias` — the Cypher variable (`"n"`, `"u"`, …)
- `prop` — the property name, or `None` when `raw` / `expr` is set
- `raw` — a validated raw Cypher reference, when a string was passed
- `expr` — a value expression, when a computed column was passed
- `desc` — `True` for descending order

### AggExpr

`runic.ogm.query.expressions.AggExpr`

Represents an aggregate expression, produced by `count()`, `avg()`, `sum_()`,
`min_()`, `max_()`, `collect()`.

- `func` — aggregate function name (`"count"`, `"avg"`, …)
- `field` — the `FieldDescriptor` or raw string the aggregate applies to
  (`"*"` for `count(*)`)
- `result_alias` — the `AS` name set by `.as_()`
- `distinct` — `True` for `collect(DISTINCT …)`

Mixing aggregates and plain values in `project()` groups by the plain values,
the way Cypher does.

### Aggregate helpers

`runic.ogm.query.expressions`

Each returns an `AggExpr`.

| Function | Emits |
|----------|-------|
| `count(field)` | `COUNT(field)` — `count("*")` for `COUNT(*)` |
| `avg(field)` | `AVG(field)` |
| `sum_(field)` | `SUM(field)` |
| `min_(field)` | `MIN(field)` |
| `max_(field)` | `MAX(field)` |
| `collect(field)` | `COLLECT(field)` |

```python
select(Order).project(Order.customer_id, sum_(Order.total).as_("revenue"))
```

---

## runic.ogm.schema — Index Declarations

### IndexSpec

`runic.ogm.schema.index_manager.IndexSpec`

Frozen dataclass declaring a single index or constraint on a node label and
property.

- `label` — graph label the index applies to
- `property` — property name to index
- `index_type` — `"RANGE"`, `"FULLTEXT"`, `"VECTOR"`, or `"UNIQUE"`

### extract_declared_specs

`runic.ogm.schema.index_manager.extract_declared_specs`

`extract_declared_specs(entity_class)` → `set[IndexSpec]` derived from the
class's `Field()` declarations:

- `unique=True` → `UNIQUE` (the backing `RANGE` is auto-created by FalkorDB)
- `index=True` without `unique` → `RANGE`
- `index_type="FULLTEXT"` → `FULLTEXT`
- `index_type="VECTOR"` → `VECTOR`
- relationship fields are skipped
- a field with both `unique=True` and `index=True` emits only `UNIQUE`

---

## runic.migrate.schema — Index & Schema Management

### IndexManager

`runic.migrate.schema.IndexManager`

`IndexManager(adapter)` — creates the indexes an entity class declares, using a
migrate adapter for the backend DDL.

- `create_indexes(entity_class, *, if_not_exists=True)` — create every index
  declared on the class
- `ensure_indexes(entity_class)` — create the missing ones only
- `create_spec(spec)` / `drop_spec(spec)` — create or drop a single `IndexSpec`

### ValidationResult

`runic.migrate.schema.ValidationResult`

Result object returned by `SchemaManager.validate_schema()`.

- `is_valid` — `True` if no issues were found
- `missing_indexes` — indexes declared on the models but absent from the graph
- `extra_indexes` — indexes in the graph that no model declares
- `errors` — messages describing anything else that failed validation

### SchemaManager

`runic.migrate.schema.SchemaManager`

`SchemaManager(adapter)` — high-level facade for schema lifecycle operations.
Every method takes the list of entity classes to work from.

- `sync_schema(entity_classes, *, drop_extra=False)` — create the declared
  indexes; `drop_extra=True` also removes undeclared ones
- `validate_schema(entity_classes)` — return a `ValidationResult`
- `get_schema_diff(entity_classes)` — a human-readable drift report
- `get_schema_info(entity_classes)` — a `SchemaInfo` snapshot of the live schema
- `ensure_entity_types(entity_classes)` — create backend-level types where the
  backend needs them (ArcadeDB)

---

## runic.ogm.exceptions

All OGM exceptions derive from `OrmError`, so one `except OrmError` catches
every case below.

### OrmError

`runic.ogm.exceptions.OrmError`

Base exception for all runic OGM errors.

### EntityNotFoundError

`runic.ogm.exceptions.EntityNotFoundError`

Raised when a requested node or edge does not exist in the graph.

### DetachedEntityError

`runic.ogm.exceptions.DetachedEntityError`

Raised when an operation is attempted on an entity that is no longer associated with a session.

### LazyLoadError

`runic.ogm.exceptions.LazyLoadError`

Raised when a lazy-loaded relation cannot be resolved (e.g. because the session is closed).

### FieldValidationError

`runic.ogm.exceptions.FieldValidationError`

Raised when a value assigned to a field fails type or constraint validation.

### MetadataError

`runic.ogm.exceptions.MetadataError`

Raised when model metadata is missing, duplicated, or otherwise inconsistent.

Backends also raise plain `NotImplementedError` — via `require_feature()` —
when a statement uses a `CypherFeature` the dialect declares unsupported. That
is deliberate: it is not a data error, it is a portability one.

::: info See also
[migration/api](../migration/api.md) — Migration API reference (`runic.migrate`)
:::
