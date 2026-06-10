# OGM API Reference

> **Note:** This is a manually-maintained API reference. For the authoritative API, read the [source on GitHub](https://github.com/jenreh/runic/tree/main/src/runic).

`runic.ogm` is a lightweight graph OGM for Cypher-based graph databases.
It follows a SQLAlchemy-style architecture: driver → session → mapper →
repository. FalkorDB, ArcadeDB, and any Bolt-compatible database are
supported via the `GraphDriver` abstraction.

---

## runic.ogm.core — Models & Fields

### Node

`runic.ogm.core.models.Node`

Base class for graph node models.

- `__label__` — graph label for the node (defaults to the class name)
- `__fields__` — mapping of field names to `FieldDescriptor` instances
- `save()` — persist the node to the graph
- `delete()` — remove the node from the graph
- `to_dict()` — serialize the node to a plain dictionary

### Edge

`runic.ogm.core.models.Edge`

Base class for graph edge (relationship) models.

- `__type__` — relationship type (defaults to the class name uppercased)
- `__fields__` — mapping of field names to `FieldDescriptor` instances
- `source` — the source node of the edge
- `target` — the target node of the edge
- `to_dict()` — serialize the edge to a plain dictionary

### Field

`runic.ogm.core.descriptors.Field`

Factory function that declares a node or edge property field. Returns a `FieldDescriptor`.

```python
class Person(Node):
    name: str = Field(default=None)
    age: int = Field(default=0)
```

### Relation

`runic.ogm.core.descriptors.Relation`

Factory function that declares a relationship attribute on a node. Returns a `FieldDescriptor` configured as a relation.

```python
class Person(Node):
    friends: list[Person] = Relation("FRIEND_OF", target=Person)
```

### FieldDescriptor

`runic.ogm.core.descriptors.FieldDescriptor`

Internal descriptor class that backs `Field()` and `Relation()` declarations.

- `field_name` — name of the field on the model class
- `field_info` — the associated `FieldInfo` metadata object
- `__get__()` — descriptor getter; returns the field value or triggers lazy load
- `__set__()` — descriptor setter; validates and stores the value

### FieldInfo

`runic.ogm.core.descriptors.FieldInfo`

Metadata container for a declared field.

- `default` — default value or factory
- `converter` — optional `TypeConverter` for serialisation/deserialisation
- `is_relation` — `True` if this field represents a relationship
- `relation_type` — Cypher relationship type string (for relations)
- `target_model` — target node class (for relations)

---

## runic.ogm.core — MetaData

### MetaData

`runic.ogm.core.metadata.MetaData`

Registry that tracks all `Node` and `Edge` model classes.

- `register(cls)` — register a model class
- `nodes` — dict of label → `NodeMeta`
- `edges` — dict of type → `EdgeMeta`
- `get_node_meta(label)` — return `NodeMeta` for the given label
- `get_edge_meta(type_)` — return `EdgeMeta` for the given type

### NodeMeta

`runic.ogm.core.metadata.NodeMeta`

Metadata record for a registered node class.

- `label` — graph label string
- `model_cls` — the Python class
- `fields` — mapping of field name → `FieldInfo`

### EdgeMeta

`runic.ogm.core.metadata.EdgeMeta`

Metadata record for a registered edge class.

- `type_` — relationship type string
- `model_cls` — the Python class
- `fields` — mapping of field name → `FieldInfo`

### get_metadata

`runic.ogm.core.metadata.get_metadata`

Module-level function that returns the global `MetaData` singleton.

---

## runic.ogm.core — Type Converters

### TypeConverter

`runic.ogm.core.types.TypeConverter`

Abstract base class for field type converters.

- `to_db(value)` — convert a Python value to its graph-database representation
- `from_db(value)` — convert a graph-database value back to Python

### DatetimeConverter

`runic.ogm.core.types.DatetimeConverter`

Converter for `datetime` fields. Serialises to ISO-8601 strings and deserialises back to `datetime` objects.

- `to_db(value)` — returns ISO-8601 string
- `from_db(value)` — returns `datetime`

### EnumConverter

`runic.ogm.core.types.EnumConverter`

Converter for `Enum` fields. Serialises to the enum value and deserialises back to the enum member.

- `to_db(value)` — returns `value.value`
- `from_db(value)` — returns `EnumClass(value)`

### Vector

`runic.ogm.core.types.Vector`

Native type for vector (embedding) fields. Wraps a list of floats and carries optional dimension metadata.

- `values` — the underlying list of floats
- `dimensions` — expected vector length (optional)

### VectorConverter

`runic.ogm.core.types.VectorConverter`

Converter that serialises `Vector` instances to lists and back.

- `to_db(value)` — returns `list[float]`
- `from_db(value)` — returns `Vector`

### GeoLocation

`runic.ogm.core.types.GeoLocation`

Native type for geographic coordinate fields.

- `latitude` — float
- `longitude` — float

### GeoLocationConverter

`runic.ogm.core.types.GeoLocationConverter`

Converter that serialises `GeoLocation` instances to dicts and back.

- `to_db(value)` — returns `{"latitude": ..., "longitude": ...}`
- `from_db(value)` — returns `GeoLocation`

---

## runic.ogm.driver — Drivers & Dialects

### FalkorDBDriver

`runic.ogm.driver.falkordb.FalkorDBDriver`

Synchronous driver for FalkorDB.

- `execute(query, params)` — run a Cypher query and return a `GraphResult`
- `close()` — release the connection

### AsyncFalkorDBDriver

`runic.ogm.driver.falkordb.AsyncFalkorDBDriver`

Asynchronous driver for FalkorDB.

- `execute(query, params)` — coroutine; run a Cypher query and return a `GraphResult`
- `close()` — coroutine; release the connection

### FalkorDBDialect

`runic.ogm.driver.falkordb.FalkorDBDialect`

Cypher dialect customisations for FalkorDB.

- `render_create_node(label, props)` — returns FalkorDB-compatible CREATE clause
- `render_index(label, field)` — returns FalkorDB-compatible index DDL

### BoltDriver

`runic.ogm.driver.bolt.BoltDriver`

Generic Bolt-protocol driver; compatible with Neo4j and ArcadeDB Bolt endpoint.

- `execute(query, params)` — run a Cypher query and return a `GraphResult`
- `close()` — release the connection

### ArcadeDBDialect

`runic.ogm.driver.arcadedb.ArcadeDBDialect`

Cypher dialect customisations for ArcadeDB.

- `render_create_node(label, props)` — returns ArcadeDB-compatible CREATE clause

### AGEDriver

`runic.ogm.driver.age.AGEDriver`

Driver for Apache AGE (PostgreSQL graph extension).

- `execute(query, params)` — run a Cypher query via AGE and return a `GraphResult`
- `close()` — release the connection

### AGEDialect

`runic.ogm.driver.age.AGEDialect`

Cypher dialect customisations for Apache AGE.

- `wrap_query(graph_name, query)` — wraps a Cypher query in the `ag_catalog.cypher()` call

### create_falkordb_driver

`runic.ogm.driver.falkordb.create_falkordb_driver`

Factory function. Creates and returns a `FalkorDBDriver` (or `AsyncFalkorDBDriver`) from connection parameters.

### create_arcadedb_driver

`runic.ogm.driver.arcadedb.create_arcadedb_driver`

Factory function. Creates and returns a `BoltDriver` configured for ArcadeDB.

### create_age_driver

`runic.ogm.driver.age.create_age_driver`

Factory function. Creates and returns an `AGEDriver` from connection parameters.

### create_driver

`runic.ogm.driver.factory.create_driver`

Generic factory function. Inspects the connection URL scheme and returns the appropriate driver instance.

---

## runic.ogm.session — Session

### Session

`runic.ogm.session.session.Session`

Synchronous unit-of-work session. Wraps a `GraphDriver` and tracks entity state.

- `add(entity)` — stage a node or edge for insertion
- `delete(entity)` — stage a node or edge for deletion
- `flush()` — write staged changes to the database
- `commit()` — flush and finalise the transaction
- `rollback()` — discard all staged changes
- `close()` — release the driver connection

### AsyncSession

`runic.ogm.session.async_session.AsyncSession`

Asynchronous counterpart to `Session`. All mutating methods are coroutines.

- `add(entity)` — stage a node or edge for insertion
- `delete(entity)` — stage a node or edge for deletion
- `flush()` — coroutine; write staged changes
- `commit()` — coroutine; flush and finalise
- `rollback()` — coroutine; discard staged changes
- `close()` — coroutine; release the driver connection

### ConnectionManager

`runic.ogm.session.connection_pool.ConnectionManager`

Synchronous connection pool manager.

- `acquire()` — return an available `Session`
- `release(session)` — return a session to the pool
- `close_all()` — close every pooled session

### AsyncConnectionManager

`runic.ogm.session.connection_pool.AsyncConnectionManager`

Asynchronous connection pool manager.

- `acquire()` — coroutine; return an available `AsyncSession`
- `release(session)` — coroutine; return a session to the pool
- `close_all()` — coroutine; close every pooled session

---

## runic.ogm.repository — Repository

### Repository

`runic.ogm.repository.repository.Repository`

Generic synchronous repository for a single `Node` or `Edge` model.

- `get(id)` — fetch an entity by primary key
- `find(**filters)` — fetch entities matching keyword filters
- `find_one(**filters)` — fetch the first matching entity
- `add(entity)` — persist a new entity
- `delete(entity)` — remove an entity
- `query()` — return a `QueryBuilder` scoped to this model

### AsyncRepository

`runic.ogm.repository.async_repository.AsyncRepository`

Asynchronous counterpart to `Repository`. All methods are coroutines.

- `get(id)` — coroutine; fetch an entity by primary key
- `find(**filters)` — coroutine; fetch entities matching keyword filters
- `find_one(**filters)` — coroutine; fetch the first matching entity
- `add(entity)` — coroutine; persist a new entity
- `delete(entity)` — coroutine; remove an entity
- `query()` — return an `AsyncQueryBuilder` scoped to this model

---

## runic.ogm.schema — Index Declarations

### IndexSpec

`runic.ogm.schema.index_manager.IndexSpec`

Declares a single index on a node label and field.

- `label` — graph label the index applies to
- `field` — field name to index
- `index_type` — `"exact"`, `"fulltext"`, or `"vector"`

### extract_declared_specs

`runic.ogm.schema.index_manager.extract_declared_specs`

Function that inspects all registered models and returns the list of `IndexSpec` instances derived from their field declarations.

## runic.migrate.schema — Index & Schema Management

### IndexManager

`runic.migrate.schema.IndexManager`

Manages index creation, deletion, and drift detection against a live database.

- `apply(specs)` — create any missing indexes from a list of `IndexSpec`
- `drop(specs)` — drop indexes matching the given specs
- `diff(specs)` — return specs that are declared but not yet present in the db

### ValidationResult

`runic.migrate.schema.ValidationResult`

Result object returned by schema validation operations.

- `is_valid` — `True` if no issues were found
- `missing` — list of `IndexSpec` missing from the database
- `extra` — list of database indexes not covered by any declared spec

### SchemaManager

`runic.migrate.schema.SchemaManager`

High-level facade for schema lifecycle operations.

- `validate()` — return a `ValidationResult` comparing declared specs against the live db
- `sync()` — apply missing indexes and remove undeclared ones
- `export()` — return a serialisable dict of the current schema state

---

## runic.ogm.exceptions

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

::: info See also
[migration/api](./migration/api.md) — Migration API reference (`runic.migrate`)
:::

---

## runic.ogm.query

### select

`runic.ogm.query.select`

Entry-point function for building a query. Returns a `QueryBuilder` pre-scoped to the given model class.

```python
q = select(Person).where(Person.age > 30).limit(10)
```

### QueryBuilder

`runic.ogm.query.builder.QueryBuilder`

Fluent query builder for synchronous Cypher queries.

- `where(expr)` — add a filter expression
- `order_by(expr)` — add an ordering expression
- `limit(n)` — limit result count
- `skip(n)` — skip the first *n* results
- `traverse(step)` — add a `TraversalStep`
- `all()` — execute and return all matching entities
- `one()` — execute and return the first matching entity
- `count()` — execute and return the result count

### AsyncQueryBuilder

`runic.ogm.query.specialised.AsyncQueryBuilder`

Asynchronous counterpart to `QueryBuilder`. `all()`, `one()`, and `count()` are coroutines.

### FulltextQueryBuilder

`runic.ogm.query.specialised.FulltextQueryBuilder`

Specialised `QueryBuilder` for fulltext index queries.

- `search(text)` — perform a fulltext search against declared fulltext indexes

### VectorQueryBuilder

`runic.ogm.query.specialised.VectorQueryBuilder`

Specialised `QueryBuilder` for vector similarity queries.

- `near(vector, k)` — perform a k-NN search against declared vector indexes

### TraversalStep

`runic.ogm.query.traversal.TraversalStep`

Represents one hop in a graph traversal.

- `relation_type` — the Cypher relationship type to traverse
- `target_model` — expected model class at the target
- `direction` — `"outgoing"`, `"incoming"`, or `"both"`
- `depth` — fixed depth or `(min, max)` range tuple

### Expr

`runic.ogm.query.expressions.Expr`

Abstract base class for all query expression types.

### FilterExpr

`runic.ogm.query.expressions.FilterExpr`

A simple binary filter expression (e.g. `field == value`).

- `field` — the field name
- `operator` — comparison operator string (`"="`, `">"`, `"<"`, etc.)
- `value` — the comparison value

### CompoundExpr

`runic.ogm.query.expressions.CompoundExpr`

Combines two expressions with `AND` or `OR`.

- `left` — left-hand `Expr`
- `right` — right-hand `Expr`
- `operator` — `"AND"` or `"OR"`

### NegatedExpr

`runic.ogm.query.expressions.NegatedExpr`

Wraps an expression with `NOT`.

- `inner` — the `Expr` to negate

### OrderExpr

`runic.ogm.query.expressions.OrderExpr`

Represents an `ORDER BY` clause.

- `field` — the field to order by
- `direction` — `"ASC"` or `"DESC"`

### AggExpr

`runic.ogm.query.expressions.AggExpr`

Represents an aggregate expression (e.g. `COUNT`, `AVG`).

- `function` — aggregate function name
- `field` — field the aggregate applies to

### count

`runic.ogm.query.expressions.count`

Helper function. Returns an `AggExpr` for `COUNT(field)`.

### avg

`runic.ogm.query.expressions.avg`

Helper function. Returns an `AggExpr` for `AVG(field)`.

### sum_

`runic.ogm.query.expressions.sum_`

Helper function. Returns an `AggExpr` for `SUM(field)`.

### min_

`runic.ogm.query.expressions.min_`

Helper function. Returns an `AggExpr` for `MIN(field)`.

### max_

`runic.ogm.query.expressions.max_`

Helper function. Returns an `AggExpr` for `MAX(field)`.

### collect

`runic.ogm.query.expressions.collect`

Helper function. Returns an `AggExpr` for `COLLECT(field)`.
