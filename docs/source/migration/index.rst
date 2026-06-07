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

   .. grid-item-card:: CLI reference
      :link: ./cli_reference
      :link-type: doc

      Every command, option, and flag documented with examples.

.. grid:: 2

   .. grid-item-card:: Operations reference
      :link: ./operations_reference
      :link-type: doc

      Full list of ``op.*`` calls available inside migration scripts.

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

.. toctree::
   :maxdepth: 1
   :caption: Tutorial

   tutorial/index

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
