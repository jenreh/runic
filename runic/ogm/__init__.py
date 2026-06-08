"""runic.ogm — lightweight graph OGM for Cypher-based graph databases."""

from runic.ogm.driver import (
    AsyncGraphDriver,
    GraphDialect,
    GraphDriver,
    GraphResult,
    TransactionalGraphDriver,
)
from runic.ogm.driver.age import AGEDialect, AGEDriver, create_age_driver
from runic.ogm.driver.arcadedb import ArcadeDBDialect, create_arcadedb_driver
from runic.ogm.driver.bolt import BoltDriver
from runic.ogm.driver.factory import create_driver
from runic.ogm.driver.falkordb import (
    AsyncFalkorDBDriver,
    FalkorDBDialect,
    FalkorDBDriver,
    create_falkordb_driver,
)
from runic.ogm.driver.memgraph import MemgraphDialect, create_memgraph_driver
from runic.ogm.driver.neo4j import Neo4jDialect, create_neo4j_driver
from runic.ogm.core.descriptors import (
    MISSING,
    Field,
    FieldDescriptor,
    FieldInfo,
    Relation,
    _NOT_LOADED,
)
from runic.ogm.core.metadata import EdgeMeta, MetaData, NodeMeta, get_metadata, metadata
from runic.ogm.core.models import Edge, Node
from runic.ogm.core.types import (
    DatetimeConverter,
    EnumConverter,
    GeoLocation,
    GeoLocationConverter,
    TypeConverter,
    Vector,
    VectorConverter,
)
from runic.ogm.exceptions import (
    DetachedEntityError,
    EntityNotFoundError,
    FieldValidationError,
    LazyLoadError,
    MetadataError,
    OrmError,
)
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.mapper.relationship_loader import RelationshipLoader
from runic.ogm.repository.async_repository import AsyncRepository
from runic.ogm.repository.repository import Repository
from runic.ogm.query import (
    AsyncQueryBuilder,
    FulltextQueryBuilder,
    QueryBuilder,
    VectorQueryBuilder,
    avg,
    collect,
    count,
    max_,
    min_,
    select,
    sum_,
)
from runic.ogm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
    NegatedExpr,
    OrderExpr,
)
from runic.ogm.schema.index_manager import IndexSpec
from runic.ogm.session.async_session import AsyncSession
from runic.ogm.session.connection_pool import AsyncConnectionManager, ConnectionManager
from runic.ogm.session.session import Session

__all__ = [  # noqa: RUF022
    # Driver / dialect
    "AGEDialect",
    "AGEDriver",
    "AsyncFalkorDBDriver",
    "AsyncGraphDriver",
    "ArcadeDBDialect",
    "BoltDriver",
    "FalkorDBDialect",
    "FalkorDBDriver",
    "GraphDialect",
    "GraphDriver",
    "GraphResult",
    "TransactionalGraphDriver",
    "MemgraphDialect",
    "Neo4jDialect",
    "create_age_driver",
    "create_arcadedb_driver",
    "create_driver",
    "create_falkordb_driver",
    "create_memgraph_driver",
    "create_neo4j_driver",
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
    # Repository
    "AsyncRepository",
    "Repository",
    # Mapper
    "Mapper",
    "RelationshipLoader",
    # Schema
    "IndexSpec",
    # Exceptions
    "DetachedEntityError",
    "EntityNotFoundError",
    "FieldValidationError",
    "LazyLoadError",
    "MetadataError",
    "OrmError",
    # Query builder
    "select",
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
