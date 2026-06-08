Migration
=========

``runic.migrate`` is an Alembic-style schema migration engine for graph
databases — FalkorDB, ArcadeDB, Neo4j, Memgraph, and Apache AGE.
It tracks every change to your graph's indexes and constraints as a versioned,
replayable script and gives you a CLI to apply, roll back, inspect, and test
those changes safely.


.. rubric:: Migration

.. grid:: 2

   .. grid-item-card:: Migration quickstart
      :link: ./quickstart
      :link-type: doc

      Install runic, run ``runic init``, write your first migration, and
      apply it — all in one page.

   .. grid-item-card:: OGM + Migration guide
      :link: ./integration
      :link-type: doc

      Three-stage workflow, Field→op translation, ordering rules, and 7
      annotated patterns — the complete lifecycle guide.

.. grid:: 2

   .. grid-item-card:: CLI reference
      :link: ./cli_reference
      :link-type: doc

      Every command, option, and flag documented with examples.

   .. grid-item-card:: Operations reference
      :link: ./operations_reference
      :link-type: doc

      Full list of ``op.*`` calls available inside migration scripts.

.. grid:: 2

   .. grid-item-card:: Schema management
      :link: ./schema
      :link-type: doc

      IndexManager and SchemaManager — declare, validate, and sync indexes.

   .. grid-item-card:: Migration API reference
      :link: ./api
      :link-type: doc

      ``runic.migrate`` — programmatic migration engine API.


----

.. toctree::
   :maxdepth: 1
   :caption: Getting started
   :hidden:

   quickstart
   integration

.. toctree::
   :maxdepth: 1
   :caption: Reference

   cli_reference

   schema
   operations_reference
   autogenerate
   branching
   testing

.. toctree::
   :maxdepth: 1
   :caption: API

   api
   limitations
