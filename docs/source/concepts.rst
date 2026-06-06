Mappings
========

This page explains the building blocks of ``runic.orm`` — Node, Edge, Field,
object states, dirty tracking, and the identity map.

Node and Edge
-------------

Every graph entity inherits from either :class:`~runic.orm.core.models.Node`
or :class:`~runic.orm.core.models.Edge`.

.. code-block:: python

   from runic.orm import Edge, Field, Node

   class Person(Node, labels=["Person"]):
       id: str = Field()
       name: str = Field()
       email: str = Field(index=True, unique=True)

   class InvitationEdge(Edge, type="INVITED_TO"):
       role: str = Field()
       status: str = Field()
       invited_at: str = Field()

**``labels``** controls which FalkorDB labels are applied.  Multi-label
nodes implement polymorphic hierarchies — see :doc:`relationships`.

**``primary_label``** (optional) is the label used in ``MATCH`` predicates
when the node has more than one label:

.. code-block:: python

   class Location(Node, labels=["Location"], primary_label="Location"):
       id: str = Field()
       title: str = Field()

   class Country(Location, labels=["Location", "Country"], primary_label="Location"):
       iso_code: str = Field(unique=True)

Field and Relation descriptors
------------------------------

Properties and relationships are declared with separate functions for a
clean separation of concerns:

* :func:`~runic.orm.core.descriptors.Field` — scalar properties, index
  hints, and constraints.
* :func:`~runic.orm.core.descriptors.Relation` — graph relationships
  (edges).

Both return :class:`~runic.orm.core.descriptors.FieldDescriptor` typed as
``Any``, so ``name: str = Field()`` is accepted by type checkers without
error.

**Field parameters**

.. list-table::
   :header-rows: 1
   :widths: 20 12 68

   * - Parameter
     - Type
     - Description
   * - ``default``
     - ``Any``
     - Python default value (evaluated lazily via ``default_factory`` for
       mutable types)
   * - ``index``
     - ``bool``
     - Create a ``RANGE`` index
   * - ``index_type``
     - ``str``
     - ``"FULLTEXT"`` or ``"VECTOR"``
   * - ``unique``
     - ``bool``
     - Unique constraint
   * - ``required``
     - ``bool``
     - Validated on save; raises :exc:`~runic.orm.exceptions.FieldValidationError`
   * - ``converter``
     - :class:`~runic.orm.core.types.TypeConverter`
     - Custom encode/decode (e.g. datetime ↔ ISO-8601 string)
   * - ``generated``
     - ``bool``
     - FalkorDB assigns the node ID on ``CREATE``

**Relation parameters**

.. list-table::
   :header-rows: 1
   :widths: 20 12 68

   * - Parameter
     - Type
     - Description
   * - ``relationship``
     - ``str``
     - Edge-type string (required)
   * - ``direction``
     - ``str``
     - ``"OUTGOING"``, ``"INCOMING"``, or ``"BOTH"`` (required)
   * - ``target``
     - ``str | type``
     - Entity class (or forward-reference string) for the other end (required)
   * - ``edge_model``
     - ``str | type``
     - Optional :class:`~runic.orm.core.models.Edge` subclass holding edge properties
   * - ``lazy``
     - ``bool``
     - Delay relationship loading (default ``True``)
   * - ``cascade``
     - ``bool``
     - Auto-add related entities when the owning entity is added to a session
   * - ``default``
     - ``Any``
     - Default value (defaults to ``None``)

Object states
-------------

Each entity lives in exactly one state at any time, mirroring SQLAlchemy:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - State
     - When the object enters it
   * - **Transient**
     - Created with ``Entity(...)``, not yet known to any session
   * - **Pending**
     - After ``session.add(entity)``; written on ``flush()``
   * - **Persistent**
     - Loaded from the graph, or after the first successful ``flush()``
   * - **Deleted**
     - After ``session.delete(entity)``; ``DETACH DELETE``d on ``flush()``
   * - **Detached**
     - After ``session.expunge(entity)`` or ``session.close()``

Dirty tracking
--------------

Two private flags drive query selection:

* ``_new`` — ``True`` until the first successful flush.
  Mapper emits ``CREATE`` when this is true.
* ``_dirty`` — ``True`` when any field is written on a persistent entity.
  Mapper emits ``MERGE … SET`` when this is true.

The descriptor ``__set__`` sets ``_dirty = True`` automatically.  The Session clears
``_dirty`` after a successful ``flush()``.

Identity map
------------

The Session keeps one Python instance per ``(EntityClass, primary_key)`` pair.
Calling ``session.get(Person, "alice")`` twice within the same session returns
the *same* object.

.. code-block:: python

   with Session(graph) as session:
       a = session.get(Person, "alice")
       b = session.get(Person, "alice")
       assert a is b   # True

Repository reads also register entities in the identity map.

Type converters
---------------

Custom Python types can be encoded/decoded with a
:class:`~runic.orm.core.types.TypeConverter`:

.. code-block:: python

   from runic.orm import DatetimeConverter, EnumConverter, Field, Node
   from datetime import datetime
   from enum import Enum

   class Status(str, Enum):
       ACTIVE = "active"
       ARCHIVED = "archived"

   class Trip(Node, labels=["Trip"]):
       id: str = Field()
       status: Status = Field(converter=EnumConverter(Status))
       created_at: datetime = Field(converter=DatetimeConverter())

Built-in converters: :class:`~runic.orm.core.types.DatetimeConverter` and
:class:`~runic.orm.core.types.EnumConverter`.  Implement
:class:`~runic.orm.core.types.TypeConverter` (``to_graph`` / ``from_graph``)
for custom types such as ``GeoPoint``.

Metadata registry
-----------------

All ``Node`` and ``Edge`` subclasses are registered automatically in the
global :data:`~runic.orm.core.metadata.metadata` singleton when the class is
defined.  Forward references in ``target=`` strings are resolved at import
time.

.. code-block:: python

   from runic.orm import metadata

   for node_meta in metadata.all_nodes():
       print(node_meta.cls.__name__, node_meta.labels)
