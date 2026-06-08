.. runic documentation master file

Welcome to **Runic**
====================

Graph schema migrations and ORM for Cypher-based graph databases.

|PyPI| |Github| |Python| |License|


.. |PyPI| image:: https://img.shields.io/pypi/v/runic-py.svg
   :target: https://pypi.org/project/runic-py/
   :alt: PyPI

.. |Github| image:: https://img.shields.io/badge/release-0.3.2-yellow?logo=github
   :target: https://github.com/jenreh/runic/tree/v0.3.2
   :alt: GitHub

.. |Python| image:: https://img.shields.io/badge/python-3.14%2B-orange.svg
   :target: https://www.python.org
   :alt: Python Support

.. |License| image:: https://img.shields.io/badge/license-MIT-green.svg
   :target: https://github.com/jenreh/runic/blob/main/LICENSE.md
   :alt: License

-----

**runic** ships two tools:

* **runic.orm** — a lightweight, graph-optimized ORM that maps Python classes
  to graph nodes and edges.  Supports FalkorDB, ArcadeDB, Neo4j,
  Memgraph, Apache AGE (PostgreSQL), and any Bolt-compatible database
  via a pluggable driver layer.
* **runic.migrate** — an Alembic-style migration engine that tracks index and
  constraint changes as versioned, replayable scripts.

.. code-block:: python

   from runic.orm import Field, Node, Repository, Session, create_driver

   class Person(Node, labels=["Person"]):
       id: str = Field()
       name: str = Field()
       email: str = Field(index=True, unique=True)

   with Session(driver) as session:
       session.add(Person(id="alice", name="Alice", email="alice@example.com"))
       session.commit()

       repo = Repository(session, Person)
       print(repo.count())   # 1

----

.. rubric:: ORM

.. grid:: 2

   .. grid-item-card:: ORM quickstart
      :link: quickstart
      :link-type: doc

      Define your first node, open a session, and persist it in under a
      minute.

   .. grid-item-card:: Core concepts
      :link: concepts
      :link-type: doc

      Node, Edge, Field, object states, dirty tracking, identity map.

.. grid:: 2

   .. grid-item-card:: Relationships
      :link: relationships
      :link-type: doc

      Lazy/eager loading, polymorphic hierarchies, edge properties.

   .. grid-item-card:: Session & Unit of Work
      :link: session
      :link-type: doc

      add · delete · get · flush · commit · rollback · expire.

.. grid:: 2

   .. grid-item-card:: Query builder
      :link: query_builder
      :link-type: doc

      Fluent filter, traversal, aggregation, fulltext and vector KNN API.

   .. grid-item-card:: Supported drivers
      :link: drivers
      :link-type: doc

      FalkorDB, ArcadeDB, and generic Bolt — feature matrix and limitations.

.. grid:: 2

   .. grid-item-card:: ORM API reference
      :link: api
      :link-type: doc

      Full autodoc reference for every public class and function.

----

.. rubric:: Migration

.. grid:: 2

   .. grid-item-card:: Migration quickstart
      :link: migration/quickstart
      :link-type: doc

      Install runic, run ``runic init``, write your first migration, and
      apply it — all in one page.

   .. grid-item-card:: CLI reference
      :link: migration/cli_reference
      :link-type: doc

      Every command, option, and flag documented with examples.

.. grid:: 2

   .. grid-item-card:: Operations reference
      :link: migration/operations_reference
      :link-type: doc

      Full list of ``op.*`` calls available inside migration scripts.

   .. grid-item-card:: Schema management
      :link: migration/schema
      :link-type: doc

      IndexManager and SchemaManager — declare, validate, and sync indexes.

.. grid:: 2

   .. grid-item-card:: Migration API reference
      :link: migration/api
      :link-type: doc

      ``runic.migrate`` — programmatic migration engine API.

----

.. toctree::
   :hidden:
   :caption: ORM

   quickstart
   concepts
   relationships
   query_builder
   session
   drivers
   api

.. toctree::
   :hidden:
   :caption: Migration

   installation
   migration/index
