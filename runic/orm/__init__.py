"""runic.orm — lightweight graph ORM for Cypher-based graph databases."""

from runic.orm.driver import AsyncGraphDriver, GraphDialect, GraphDriver, GraphResult
from runic.orm.driver.arcadedb import ArcadeDBDialect, create_arcadedb_driver
from runic.orm.driver.bolt import BoltDriver
from runic.orm.driver.factory import create_driver
from runic.orm.driver.falkordb import (
    AsyncFalkorDBDriver,
    FalkorDBDialect,
    FalkorDBDriver,
    create_falkordb_driver,
)
from runic.orm.core.descriptors import (
    MISSING,
    Field,
    FieldDescriptor,
    FieldInfo,
    Relation,
    _NOT_LOADED,
)
from runic.orm.core.metadata import EdgeMeta, MetaData, NodeMeta, get_metadata, metadata
from runic.orm.core.models import Edge, Node
from runic.orm.core.types import (
    DatetimeConverter,
    EnumConverter,
    GeoLocation,
    GeoLocationConverter,
    TypeConverter,
    Vector,
    VectorConverter,
)
from runic.orm.exceptions import (
    DetachedEntityError,
    EntityNotFoundError,
    FieldValidationError,
    LazyLoadError,
    MetadataError,
    OrmError,
)
from runic.orm.mapper.mapper import Mapper
from runic.orm.mapper.relationship_loader import RelationshipLoader
from runic.orm.repository.async_repository import AsyncRepository
from runic.orm.repository.pagination import Page, Pageable
from runic.orm.repository.repository import Repository
from runic.orm.query import (
    AsyncQueryBuilder,
    FulltextQueryBuilder,
    QueryBuilder,
    VectorQueryBuilder,
    avg,
    collect,
    count,
    max_,
    min_,
    sum_,
)
from runic.orm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
    NegatedExpr,
    OrderExpr,
)
from runic.orm.schema.index_manager import IndexManager, IndexSpec
from runic.orm.schema.schema_manager import SchemaManager, ValidationResult
from runic.orm.session.async_session import AsyncSession
from runic.orm.session.connection_pool import AsyncConnectionManager, ConnectionManager
from runic.orm.session.session import Session

__all__ = [  # noqa: RUF022
    # Driver / dialect
    "AsyncFalkorDBDriver",
    "AsyncGraphDriver",
    "ArcadeDBDialect",
    "BoltDriver",
    "FalkorDBDialect",
    "FalkorDBDriver",
    "GraphDialect",
    "GraphDriver",
    "GraphResult",
    "create_arcadedb_driver",
    "create_driver",
    "create_falkordb_driver",
    # Core
    "MISSING",
    "_NOT_LOADED",
    "Edge",
    "EdgeMeta",
    "Field",
    "FieldDescriptor",
    "FieldInfo",
    "Relation",
    "Node",
    "NodeMeta",
    "MetaData",
    "get_metadata",
    "metadata",
    # Types / converters
    "DatetimeConverter",
    "EnumConverter",
    "GeoLocation",
    "GeoLocationConverter",
    "TypeConverter",
    "Vector",
    "VectorConverter",
    # Session / connection
    "AsyncConnectionManager",
    "AsyncSession",
    "ConnectionManager",
    "Session",
    # Repository / pagination
    "AsyncRepository",
    "Page",
    "Pageable",
    "Repository",
    # Mapper
    "Mapper",
    "RelationshipLoader",
    # Schema
    "IndexManager",
    "IndexSpec",
    "SchemaManager",
    "ValidationResult",
    # Exceptions
    "DetachedEntityError",
    "EntityNotFoundError",
    "FieldValidationError",
    "LazyLoadError",
    "MetadataError",
    "OrmError",
    # Query builder
    "AsyncQueryBuilder",
    "FulltextQueryBuilder",
    "QueryBuilder",
    "VectorQueryBuilder",
    # Expression types
    "AggExpr",
    "CompoundExpr",
    "Expr",
    "FilterExpr",
    "NegatedExpr",
    "OrderExpr",
    # Aggregation helpers
    "avg",
    "collect",
    "count",
    "max_",
    "min_",
    "sum_",
]
