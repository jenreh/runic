API Reference
=============

This page documents the public Python API for embedding runic in application
code or extending it.

----

runic.migrate.Runic
-----------

:class:`~runic.migrate.context.Runic` is the single class a developer needs.  It
combines all DB-connected operations (upgrade, downgrade, stamp, current) with
offline DAG queries (history, heads, revision creation) in one coherent API.

.. autoclass:: runic.migrate.context.Runic
   :members: upgrade, downgrade, stamp, current, validate,
             enable_preview, preview_log,
             get_revision_message, get_history, get_heads, get_branch_points,
             create_revision, show_revision,
             adapter, target_manifest, script_location
   :show-inheritance:

.. autoexception:: runic.migrate.context.IrreversibleMigrationError
   :show-inheritance:

Programmatic usage example
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from pathlib import Path
   from runic import Runic
   from runic.migrate.adapters import create_adapter

   # URL variant (credentials embedded in the connection string)
   adapter = create_adapter(
       "falkordb",
       url="falkor://:mypassword@localhost:6379",
       graph_name="my_graph",
   )
   # Params variant (explicit host / port / auth)
   # adapter = create_adapter(
   #     "falkordb",
   #     host="localhost", port=6379,
   #     password="mypassword",
   #     graph_name="my_graph",
   # )

   runic = Runic(adapter, script_location=Path("runic/"))

   # Validate checksums before upgrading
   errors = runic.migrate.validate()
   if errors:
       raise RuntimeError("\n".join(errors))

   runic.migrate.upgrade("head", installed_by="deploy-bot")
   print("current:", runic.migrate.current())

   history = runic.migrate.get_history()
   for entry in history:
       print(entry.revision, entry.message)

   runic.migrate.downgrade("base")

----

runic.migrate.init
----------

.. autofunction:: runic.migrate.service.init

----

runic.migrate.context (env.py singleton)
---------------------------------

The ``runic.migrate.context`` module also exposes a module-level singleton API that
``env.py`` uses so the CLI can discover the configured context after executing
the file.  **SDK users should prefer instantiating** :class:`~runic.migrate.context.Runic`
**directly** rather than using this API.

.. autofunction:: runic.migrate.context.configure

.. autofunction:: runic.migrate.context.get

.. autofunction:: runic.migrate.context.is_preview

----

runic.migrate.adapters
--------------

.. autofunction:: runic.migrate.adapters.create_adapter

----

runic.migrate.operations
----------------

.. autoclass:: runic.migrate.operations.GraphOperations
   :members:
   :show-inheritance:

----

runic.migrate.manifest
--------------

Schema manifest classes used with autogenerate.  See :doc:`autogenerate` for
usage examples.

.. autoclass:: runic.migrate.manifest.SchemaManifest
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.migrate.manifest.RangeIndex
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.migrate.manifest.FulltextIndex
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.migrate.manifest.VectorIndex
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.migrate.manifest.UniqueConstraint
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: runic.migrate.manifest.MandatoryConstraint
   :members:
   :show-inheritance:
   :no-index:

----

runic.migrate.script
------------

Internal revision DAG types.  These are returned by methods on
:class:`~runic.migrate.context.Runic` but you rarely need to construct them directly.

.. autoclass:: runic.migrate.script.Revision
   :members:
   :show-inheritance:

.. autoclass:: runic.migrate.script.RevisionInfo
   :members:
   :show-inheritance:

.. autoexception:: runic.migrate.script.RevisionNotFound
   :show-inheritance:

.. autoexception:: runic.migrate.script.AmbiguousRevision
   :show-inheritance:

----

runic.migrate.exceptions
----------------

.. autoexception:: runic.migrate.exceptions.MultipleHeadsError
   :show-inheritance:

.. autoexception:: runic.migrate.exceptions.MultipleBasesError
   :show-inheritance:

.. autoexception:: runic.migrate.exceptions.ConstraintFailedError
   :show-inheritance:

.. autoexception:: runic.migrate.exceptions.ConstraintTimeoutError
   :show-inheritance:

----

runic.migrate.testing
-------------

Pytest fixtures for integration tests.  Requires ``falkordblite``.

.. autofunction:: runic.migrate.testing.falkordb_graph

.. autofunction:: runic.migrate.testing.runic_context
