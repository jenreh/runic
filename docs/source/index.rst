.. runic documentation master file

Welcome to **Runic**
====================

Graph Schema Migrations for FalkorDB

|PyPI| |Python| |License|


.. |PyPI| image:: https://img.shields.io/pypi/v/runic-migrate.svg
   :target: https://pypi.org/project/runic-migrate/
   :alt: PyPI

.. |Python| image:: https://img.shields.io/badge/python-3.14%2B-orange.svg
   :target: https://www.python.org
   :alt: Python Support

.. |License| image:: https://img.shields.io/badge/license-MIT-green.svg
   :target: https://github.com/jenreh/runic/blob/main/LICENSE.md
   :alt: License

Documentation for version: 0.1.12.

-----

**runic** is a lightweight, Alembic-style migration framework for
`FalkorDB <https://falkordb.com>`_ graph databases.  It tracks every change
to your graph's indexes and constraints as a versioned, replayable script and
gives you a CLI to apply, roll back, inspect, and test those changes safely.

.. code-block:: bash

   $ runic init
   $ runic revision -m "add person email index"
   # edit the generated file, then:
   $ runic upgrade
   Upgraded to: head

.. admonition:: Key concepts

   * **Revision** — a Python file that defines ``upgrade(op)`` and
     ``downgrade(op)`` functions for one schema change.
   * **op** — the operations proxy; your migrations call
     ``op.create_range_index(...)``, ``op.create_constraint(...)``, etc.
   * **env.py** — your project's connection script, executed by the CLI on
     every command that needs a live database.
   * **Version node** — a ``_FalkorMigrateVersion`` node stored inside the
     graph itself that tracks which revision is currently applied.

----

.. grid:: 2

   .. grid-item-card:: Migration — get started
      :link: migration/quickstart
      :link-type: doc

      Install runic, run ``runic init``, write your first migration, and
      apply it — all in one page.

   .. grid-item-card:: Migration tutorial
      :link: migration/tutorial/index
      :link-type: doc

      Step-by-step walkthroughs covering the full workflow: creating
      revisions, applying and rolling back, branching, and testing.

.. grid:: 2

   .. grid-item-card:: CLI reference
      :link: migration/cli_reference
      :link-type: doc

      Every command, option, and flag documented with examples.

   .. grid-item-card:: Operations reference
      :link: migration/operations_reference
      :link-type: doc

      Full list of ``op.*`` calls available inside migration scripts.

.. grid:: 2

   .. grid-item-card:: ORM API reference
      :link: api
      :link-type: doc

      ``runic.orm`` — models, sessions, repositories, and type converters.

   .. grid-item-card:: Migration API reference
      :link: migration/api
      :link-type: doc

      ``runic.migrate`` — programmatic migration engine API.

   .. grid-item-card:: Limitations
      :link: limitations
      :link-type: doc

      What runic explicitly does **not** cover, and why.


.. toctree::
   :hidden:
   :caption: Getting started

   installation

.. toctree::
   :hidden:
   :caption: Migration

   migration/index

.. toctree::
   :hidden:
   :caption: ORM & API

   api
   limitations
