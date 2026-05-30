API Reference
=============

This page documents the public Python API for embedding runic in application
code or extending it.

----

runic.Runic
-----------

:class:`~runic.context.Runic` is the single class a developer needs.  It
combines all DB-connected operations (upgrade, downgrade, stamp, current) with
offline DAG queries (history, heads, revision creation) in one coherent API.

.. autoclass:: runic.context.Runic
   :members: upgrade, downgrade, stamp, current, enable_preview, preview_log,
             get_revision_message, get_history, get_heads, get_branch_points,
             create_revision, show_revision,
             connection, graph, target_manifest, script_location
   :show-inheritance:

.. autoexception:: runic.context.IrreversibleMigrationError
   :show-inheritance:

Programmatic usage example
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from pathlib import Path
   from falkordb import FalkorDB
   from runic import Runic

   db = FalkorDB.from_url("falkor://localhost:6379")
   graph = db.select_graph("my_graph")

   runic = Runic(connection=db, graph=graph, script_location=Path("runic/"))

   runic.upgrade("head")
   print("current:", runic.current())

   history = runic.get_history()
   for entry in history:
       print(entry.revision, entry.message)

   runic.downgrade("base")

----

runic.init
----------

.. autofunction:: runic.service.init

----

runic.context (env.py singleton)
---------------------------------

The ``runic.context`` module also exposes a module-level singleton API that
``env.py`` uses so the CLI can discover the configured context after executing
the file.  **SDK users should prefer instantiating** :class:`~runic.context.Runic`
**directly** rather than using this API.

.. autofunction:: runic.context.configure

.. autofunction:: runic.context.get

.. autofunction:: runic.context.is_preview

----

runic.operations
----------------

.. autoclass:: runic.operations.GraphOperations
   :members:
   :show-inheritance:

.. autoexception:: runic.operations.ConstraintFailedError
   :show-inheritance:

.. autoexception:: runic.operations.ConstraintTimeoutError
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

Internal revision DAG types.  These are returned by methods on
:class:`~runic.context.Runic` but you rarely need to construct them directly.

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

.. autofunction:: runic.testing.runic_context
