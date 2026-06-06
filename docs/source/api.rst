ORM API Reference
=================

``runic.orm`` is a lightweight graph ORM that maps Python classes to FalkorDB
nodes and edges.  It follows a SQLAlchemy-style architecture: models →
metadata → session → repository.

----

runic.orm.core — Models & Fields
---------------------------------

.. autoclass:: runic.orm.core.models.Node
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.models.Edge
   :members:
   :show-inheritance:

.. autofunction:: runic.orm.core.descriptors.Field

.. autofunction:: runic.orm.core.descriptors.Relation

.. autoclass:: runic.orm.core.descriptors.FieldDescriptor
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.descriptors.FieldInfo
   :members:
   :show-inheritance:

----

runic.orm.core — MetaData
--------------------------

.. autoclass:: runic.orm.core.metadata.MetaData
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.metadata.NodeMeta
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.metadata.EdgeMeta
   :members:
   :show-inheritance:

.. autofunction:: runic.orm.core.metadata.get_metadata

----

runic.orm.core — Type Converters
----------------------------------

.. autoclass:: runic.orm.core.types.TypeConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.types.DatetimeConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.types.EnumConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.types.Vector
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.types.VectorConverter
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.types.GeoLocation
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.core.types.GeoLocationConverter
   :members:
   :show-inheritance:

----

runic.orm.session — Session
-----------------------------

.. autoclass:: runic.orm.session.session.Session
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.session.async_session.AsyncSession
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.session.connection_pool.ConnectionManager
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.session.connection_pool.AsyncConnectionManager
   :members:
   :show-inheritance:

----

runic.orm.repository — Repository & Pagination
------------------------------------------------

.. autoclass:: runic.orm.repository.repository.Repository
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.repository.async_repository.AsyncRepository
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.repository.pagination.Pageable
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.repository.pagination.Page
   :members:
   :show-inheritance:

----

runic.orm.schema — Index & Schema Management
---------------------------------------------

.. autoclass:: runic.orm.schema.index_manager.IndexSpec
   :members:
   :show-inheritance:

.. autofunction:: runic.orm.schema.index_manager.extract_declared_specs

.. autofunction:: runic.orm.schema.index_manager.parse_existing_specs

.. autoclass:: runic.orm.schema.index_manager.IndexManager
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.schema.schema_manager.ValidationResult
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.schema.schema_manager.SchemaManager
   :members:
   :show-inheritance:

----

runic.orm.exceptions
---------------------

.. autoexception:: runic.orm.exceptions.OrmError
   :show-inheritance:

.. autoexception:: runic.orm.exceptions.EntityNotFoundError
   :show-inheritance:

.. autoexception:: runic.orm.exceptions.DetachedEntityError
   :show-inheritance:

.. autoexception:: runic.orm.exceptions.LazyLoadError
   :show-inheritance:

.. autoexception:: runic.orm.exceptions.FieldValidationError
   :show-inheritance:

.. autoexception:: runic.orm.exceptions.MetadataError
   :show-inheritance:

.. seealso::

   :doc:`migration/api` — Migration API reference (``runic.migrate``)

----

runic.orm.query
---------------

.. autoclass:: runic.orm.query.builder.QueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.builder.AsyncQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.builder.FulltextQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.builder.VectorQueryBuilder
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.traversal.TraversalStep
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: runic.orm.query.expressions.Expr
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.query.expressions.FilterExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.query.expressions.CompoundExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.query.expressions.NegatedExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.query.expressions.OrderExpr
   :members:
   :show-inheritance:

.. autoclass:: runic.orm.query.expressions.AggExpr
   :members:
   :show-inheritance:

.. autofunction:: runic.orm.query.expressions.count

.. autofunction:: runic.orm.query.expressions.avg

.. autofunction:: runic.orm.query.expressions.sum_

.. autofunction:: runic.orm.query.expressions.min_

.. autofunction:: runic.orm.query.expressions.max_

.. autofunction:: runic.orm.query.expressions.collect

