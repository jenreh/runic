API Reference
=============

This page documents the public Python API for embedding runic in application
code or extending it.

----

runic.context
-------------

The ``runic.context`` module manages the module-level singleton used by
``env.py`` and provides the ``MigrationContext`` class for programmatic
access.

.. autofunction:: runic.context.configure

.. autofunction:: runic.context.get

.. autofunction:: runic.context.is_preview

.. autoclass:: runic.context.MigrationContext
   :members: current, upgrade, downgrade, stamp, enable_preview, preview_log,
             get_revision_message
   :show-inheritance:

.. autoexception:: runic.context.IrreversibleMigrationError
   :show-inheritance:

Programmatic usage example
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from pathlib import Path
   from runic.adapters.falkordb import FalkorDBAdapter
   from runic.context import configure, get

   adapter = FalkorDBAdapter.from_url("falkor://localhost:6379", "my_graph")
   configure(adapter, script_location=Path("runic"))
   ctx = get()

   ctx.upgrade("head")
   print("current:", ctx.current())

   ctx.downgrade("base")

----

runic.adapters
--------------

The adapter layer decouples runic's core from any specific database client.
The ``GraphAdapter`` protocol defines the interface every backend must satisfy.
``FalkorDBAdapter`` is the built-in implementation for FalkorDB.

.. autoclass:: runic.adapters.GraphAdapter
   :members:
   :show-inheritance:

.. autoclass:: runic.adapters.falkordb.FalkorDBAdapter
   :members: from_url, fork
   :show-inheritance:

.. autoexception:: runic.adapters.falkordb.ConstraintFailedError
   :show-inheritance:

.. autoexception:: runic.adapters.falkordb.ConstraintTimeoutError
   :show-inheritance:

----

runic.service
-------------

``RunicService`` is a facade for operations that do **not** require a database
connection: creating revisions, querying history, and inspecting the DAG.

.. autoclass:: runic.service.RunicService
   :members:
   :show-inheritance:

----

runic.operations
----------------

.. autoclass:: runic.operations.GraphOperations
   :members:
   :show-inheritance:

----

runic.manifest
--------------

Schema manifest classes used with autogenerate.  See :doc:`autogenerate` for
usage examples.

.. autoclass:: runic.manifest.SchemaManifest
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.manifest.RangeIndex
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.manifest.FulltextIndex
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.manifest.VectorIndex
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.manifest.UniqueConstraint
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.manifest.MandatoryConstraint
   :members:
   :show-inheritance:
   :no-index:

----

runic.script
------------

.. autoclass:: runic.script.ScriptDirectory
   :members:
   :show-inheritance:

.. autoclass:: runic.script.Revision
   :members:
   :show-inheritance:

.. autoclass:: runic.script.RevisionInfo
   :members:
   :show-inheritance:

.. autoexception:: runic.script.RevisionNotFound
   :show-inheritance:

.. autoexception:: runic.script.AmbiguousRevision
   :show-inheritance:

----

runic.exceptions
----------------

.. autoexception:: runic.exceptions.MultipleHeadsError
   :show-inheritance:

.. autoexception:: runic.exceptions.MultipleBasesError
   :show-inheritance:

----

runic.testing
-------------

Pytest fixtures for integration tests.  Requires ``falkordblite``.

.. autofunction:: runic.testing.falkordb_graph

.. autofunction:: runic.testing.falkordb_adapter

.. autofunction:: runic.testing.runic_context
