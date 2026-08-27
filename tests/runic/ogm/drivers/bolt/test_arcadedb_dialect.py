"""Unit tests for ArcadeDBDialect."""

from __future__ import annotations

from unittest.mock import MagicMock

from runic.ogm.driver.arcadedb import (
    _ARCADE_DIALECT,
    ArcadeDBDialect,
    create_arcadedb_driver,
)
from runic.ogm.driver.bolt import BoltEdge, BoltNode


class TestArcadeDBDialectGeneratedIdWhere:
    def test_matches_on_element_id(self) -> None:
        assert (
            _ARCADE_DIALECT.generated_id_where("n", "pk") == "WHERE elementId(n) = $pk"
        )

    def test_never_uses_cypher_id(self) -> None:
        # ArcadeDB's id() width is a server setting, so the client must not
        # reconstruct it — see docs/ogm/drivers.md.
        assert "id(n) =" not in _ARCADE_DIALECT.generated_id_where("n", "pk")

    def test_alias_substituted(self) -> None:
        result = _ARCADE_DIALECT.generated_id_where("node", "node_id")
        assert "node" in result
        assert "$node_id" in result


class TestArcadeDBDialectGeneratedIdsWhere:
    def test_matches_batch_on_element_id(self) -> None:
        predicate, params = _ARCADE_DIALECT.generated_ids_where("n", ["#1:0", "#1:1"])
        assert predicate == "elementId(n) IN $__pks"
        assert params == {"__pks": ["#1:0", "#1:1"]}


class TestArcadeDBDialectCypherFnForField:
    def test_returns_none_always(self) -> None:
        fi = MagicMock()
        assert _ARCADE_DIALECT.cypher_fn_for_field(fi) is None

    def test_geo_field_returns_none(self) -> None:
        from runic.ogm.core.types import GeoLocationConverter

        fi = MagicMock()
        fi.field.converter = GeoLocationConverter()
        assert _ARCADE_DIALECT.cypher_fn_for_field(fi) is None


class TestArcadeDBDialectSupportsGeoUpdate:
    def test_supports_geo_update_false(self) -> None:
        assert ArcadeDBDialect.supports_geo_update is False


class TestArcadeDBDialectFulltextCallRaises:
    def test_raises(self) -> None:
        import pytest

        with pytest.raises(NotImplementedError, match="ArcadeDB"):
            _ARCADE_DIALECT.fulltext_call("Label", "n", "q")


class TestArcadeDBDialectWrappers:
    def test_wrap_node_returns_bolt_node(self) -> None:
        raw = MagicMock()
        raw.element_id = "#1:0"
        node = _ARCADE_DIALECT.wrap_node(raw)
        assert isinstance(node, BoltNode)

    def test_wrapped_node_exposes_rid_unchanged(self) -> None:
        raw = MagicMock()
        raw.element_id = "#1:0"
        assert _ARCADE_DIALECT.wrap_node(raw).element_id == "#1:0"

    def test_wrap_edge_returns_bolt_edge(self) -> None:
        raw = MagicMock()
        node = _ARCADE_DIALECT.wrap_edge(raw)
        assert isinstance(node, BoltEdge)


class TestCreateArcadedbDriver:
    def test_returns_bolt_driver(self) -> None:
        from unittest.mock import patch

        from runic.ogm.driver.bolt import BoltDriver

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
