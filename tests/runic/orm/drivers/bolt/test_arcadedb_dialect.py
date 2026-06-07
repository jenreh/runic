"""Unit tests for ArcadeDBDialect."""

from __future__ import annotations

from unittest.mock import MagicMock

from runic.orm.driver.arcadedb import (
    _ARCADE_DIALECT,
    ArcadeDBDialect,
    ArcadeDBNode,
    create_arcadedb_driver,
)
from runic.orm.driver.bolt import BoltEdge


class TestArcadeDBDialectGeneratedIdWhere:
    def test_basic(self) -> None:
        assert _ARCADE_DIALECT.generated_id_where("n", "pk") == "WHERE id(n) = $pk"

    def test_alias_substituted(self) -> None:
        result = _ARCADE_DIALECT.generated_id_where("node", "node_id")
        assert "node" in result
        assert "$node_id" in result


class TestArcadeDBDialectCypherFnForField:
    def test_returns_none_always(self) -> None:
        fi = MagicMock()
        assert _ARCADE_DIALECT.cypher_fn_for_field(fi) is None

    def test_geo_field_returns_none(self) -> None:
        from runic.orm.core.types import GeoLocationConverter

        fi = MagicMock()
        fi.field.converter = GeoLocationConverter()
        assert _ARCADE_DIALECT.cypher_fn_for_field(fi) is None


class TestArcadeDBDialectSupportsGeoUpdate:
    def test_supports_geo_update_true(self) -> None:
        assert ArcadeDBDialect.supports_geo_update is True


class TestArcadeDBDialectFulltextCallRaises:
    def test_raises(self) -> None:
        import pytest

        with pytest.raises(NotImplementedError, match="ArcadeDB"):
            _ARCADE_DIALECT.fulltext_call("Label", "n", "q")


class TestArcadeDBDialectWrappers:
    def test_wrap_node_returns_arcadedb_node(self) -> None:
        raw = MagicMock()
        raw.element_id = "10"
        node = _ARCADE_DIALECT.wrap_node(raw)
        assert isinstance(node, ArcadeDBNode)

    def test_wrap_edge_returns_bolt_edge(self) -> None:
        raw = MagicMock()
        node = _ARCADE_DIALECT.wrap_edge(raw)
        assert isinstance(node, BoltEdge)


class TestArcadeDBNodeElementId:
    def test_element_id_divided_by_two(self) -> None:
        raw = MagicMock()
        raw.element_id = "20"
        node = ArcadeDBNode(raw)
        assert node.element_id == 10

    def test_odd_element_id_floored(self) -> None:
        raw = MagicMock()
        raw.element_id = "7"
        node = ArcadeDBNode(raw)
        assert node.element_id == 3


class TestCreateArcadedbDriver:
    def test_returns_bolt_driver(self) -> None:
        from unittest.mock import patch

        from runic.orm.driver.bolt import BoltDriver

        with patch("neo4j.GraphDatabase.driver"):
            driver = create_arcadedb_driver(
                host="localhost",
                port=2424,
                database="testdb",
                username="root",
                password="secret",
            )
        assert isinstance(driver, BoltDriver)
        assert driver.dialect is _ARCADE_DIALECT
