Schema management
=================

``runic.orm`` provides two utilities for keeping FalkorDB indexes and
constraints in sync with your model declarations:
:class:`~runic.orm.schema.index_manager.IndexManager` (fine-grained create)
and :class:`~runic.orm.schema.schema_manager.SchemaManager` (validate + diff
+ sync).

Both utilities bind to a **graph handle**, not a Session.

.. seealso::

   `examples/orm/05_schema_management.py <https://github.com/jenreh/runic/blob/main/examples/orm/05_schema_management.py>`_
      Runnable example: ``IndexManager``, ``SchemaManager`` validate/diff/sync, and a typical startup pattern.


Declaring indexes on models
---------------------------

Index hints live on :func:`~runic.orm.core.descriptors.Field` parameters:

.. code-block:: python

   from runic.orm import Field, Node

   class Person(Node, labels=["Person"]):
       id: str = Field()
       email: str = Field(index=True, unique=True)   # unique constraint + backing RANGE
       bio: str = Field(index_type="FULLTEXT")        # fulltext index
       embedding: list[float] = Field(index_type="VECTOR")  # vector index

   class Trip(Node, labels=["Trip"]):
       id: str = Field()
       title: str = Field(index_type="FULLTEXT")
       start_date: str = Field(index=True)

IndexManager
------------

Creates the indexes declared on your model classes:

.. code-block:: python

   from runic.orm import IndexManager

   manager = IndexManager(graph)

   # Create all indexes for a class (skips existing by default)
   manager.create_indexes(Person, if_not_exists=True)
   manager.create_indexes(Trip)

   # Ensure all declared indexes exist (alias for create_indexes)
   manager.ensure_indexes(Person)

SchemaManager
-------------

Compares declared indexes against FalkorDB's actual state:

.. code-block:: python

   from runic.orm import SchemaManager

   schema = SchemaManager(graph)

   # Validate
   result = schema.validate_schema([Person, Trip])
   if not result.is_valid:
       print("Missing:", result.missing_indexes)
       print("Extra:  ", result.extra_indexes)

   # Create missing, optionally drop extras
   schema.sync_schema([Person, Trip], drop_extra=False)

   # Human-readable diff
   diff = schema.get_schema_diff([Person, Trip])
   print(diff)

   # Full diagnostics
   info = schema.get_schema_info([Person, Trip])

ValidationResult fields
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Field
     - Description
   * - ``is_valid``
     - ``True`` when declared indexes exactly match the graph
   * - ``missing_indexes``
     - Declared but not yet created in FalkorDB
   * - ``extra_indexes``
     - Present in FalkorDB but not declared on any model
   * - ``errors``
     - Any errors encountered during introspection

Typical startup pattern
-----------------------

.. code-block:: python

   from falkordb import FalkorDB
   from runic.orm import SchemaManager

   db = FalkorDB(host="localhost", port=6379)
   graph = db.select_graph("myapp")

   # Apply any missing indexes at startup
   schema = SchemaManager(graph)
   schema.sync_schema([Person, Trip, Location, Country], drop_extra=False)

.. note::

   ``runic.orm`` does not manage migrations.  For versioned, replayable
   schema changes use :doc:`runic.migrate <../migration/index>`.
