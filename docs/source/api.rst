OGM API Reference
=================

``runic.ogm`` is a lightweight graph OGM for Cypher-based graph databases.
It follows a SQLAlchemy-style architecture: driver → session → mapper →
repository.  FalkorDB, ArcadeDB, and any Bolt-compatible database are
supported via the :class:`~runic.ogm.driver.GraphDriver` abstraction.

----

runic.ogm.core — Models & Fields
---------------------------------

.. autoclass:: runic.ogm.core.models.Node
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.models.Edge
   :members:
   :show-inheritance:

.. autofunction:: runic.ogm.core.descriptors.Field

.. autofunction:: runic.ogm.core.descriptors.Relation

.. autoclass:: runic.ogm.core.descriptors.FieldDescriptor
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.descriptors.FieldInfo
   :members:
   :show-inheritance:

----

runic.ogm.core — MetaData
--------------------------

.. autoclass:: runic.ogm.core.metadata.MetaData
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.metadata.NodeMeta
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.metadata.EdgeMeta
   :members:
   :show-inheritance:

.. autofunction:: runic.ogm.core.metadata.get_metadata

----

runic.ogm.core — Type Converters
----------------------------------

.. autoclass:: runic.ogm.core.types.TypeConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.types.DatetimeConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.types.EnumConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.types.Vector
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.types.VectorConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.types.GeoLocation
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.core.types.GeoLocationConverter
   :members:
   :show-inheritance:

----

runic.ogm.driver — Drivers & Dialects
--------------------------------------

.. autoclass:: runic.ogm.driver.falkordb.FalkorDBDriver
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.driver.falkordb.AsyncFalkorDBDriver
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.driver.falkordb.FalkorDBDialect
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.driver.bolt.BoltDriver
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.driver.arcadedb.ArcadeDBDialect
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.driver.age.AGEDriver
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.driver.age.AGEDialect
   :members:
   :show-inheritance:

.. autofunction:: runic.ogm.driver.falkordb.create_falkordb_driver

.. autofunction:: runic.ogm.driver.arcadedb.create_arcadedb_driver

.. autofunction:: runic.ogm.driver.age.create_age_driver

.. autofunction:: runic.ogm.driver.factory.create_driver

----

runic.ogm.session — Session
-----------------------------

.. autoclass:: runic.ogm.session.session.Session
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.session.async_session.AsyncSession
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.session.connection_pool.ConnectionManager
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.session.connection_pool.AsyncConnectionManager
   :members:
   :show-inheritance:

----

runic.ogm.repository — Repository
---------------------------------

.. autoclass:: runic.ogm.repository.repository.Repository
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.repository.async_repository.AsyncRepository
   :members:
   :show-inheritance:

----

runic.ogm.schema — Index declarations
---------------------------------------------

.. autoclass:: runic.ogm.schema.index_manager.IndexSpec
   :members:
   :show-inheritance:

.. autofunction:: runic.ogm.schema.index_manager.extract_declared_specs

runic.migrate.schema — Index & Schema Management
-------------------------------------------------

.. autoclass:: runic.migrate.schema.IndexManager
   :members:
   :show-inheritance:

.. autoclass:: runic.migrate.schema.ValidationResult
   :members:
   :show-inheritance:

.. autoclass:: runic.migrate.schema.SchemaManager
   :members:
   :show-inheritance:

----

runic.ogm.exceptions
---------------------

.. autoexception:: runic.ogm.exceptions.OrmError
   :show-inheritance:

.. autoexception:: runic.ogm.exceptions.EntityNotFoundError
   :show-inheritance:

.. autoexception:: runic.ogm.exceptions.DetachedEntityError
   :show-inheritance:

.. autoexception:: runic.ogm.exceptions.LazyLoadError
   :show-inheritance:

.. autoexception:: runic.ogm.exceptions.FieldValidationError
   :show-inheritance:

.. autoexception:: runic.ogm.exceptions.MetadataError
   :show-inheritance:

.. seealso::

   :doc:`migration/api` — Migration API reference (``runic.migrate``)

----

runic.ogm.query
---------------

.. autofunction:: runic.ogm.query.select

.. autoclass:: runic.ogm.query.builder.QueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.specialised.AsyncQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.specialised.FulltextQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.specialised.VectorQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.traversal.TraversalStep
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.expressions.Expr
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.expressions.FilterExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.expressions.CompoundExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.expressions.NegatedExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.expressions.OrderExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.ogm.query.expressions.AggExpr
   :members:
   :show-inheritance:

.. autofunction:: runic.ogm.query.expressions.count

.. autofunction:: runic.ogm.query.expressions.avg

.. autofunction:: runic.ogm.query.expressions.sum_

.. autofunction:: runic.ogm.query.expressions.min_

.. autofunction:: runic.ogm.query.expressions.max_

.. autofunction:: runic.ogm.query.expressions.collect
