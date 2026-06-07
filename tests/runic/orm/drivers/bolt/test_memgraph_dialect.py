"""Unit tests for MemgraphDialect and create_memgraph_driver."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from runic.orm.driver.bolt import BoltDriver, BoltEdge, BoltNode
from runic.orm.driver.memgraph import (
    _MEMGRAPH_DIALECT,
    MemgraphDialect,
    create_memgraph_driver,
)


class TestMemgraphDialectGeneratedIdWhere:
    def test_basic(self) -> None:
        assert _MEMGRAPH_DIALECT.generated_id_where("n", "pk") == "WHERE id(n) = $pk"

    def test_alias_and_param_are_substituted(self) -> None:
        result = _MEMGRAPH_DIALECT.generated_id_where("node", "node_id")
        assert "node" in result
        assert "$node_id" in result


class TestMemgraphDialectCypherFnForField:
    def test_returns_none_always(self) -> None:
        fi = MagicMock()
        assert _MEMGRAPH_DIALECT.cypher_fn_for_field(fi) is None

    def test_ignores_interned_field(self) -> None:
        fi = MagicMock()
        fi.field.interned = True
        assert _MEMGRAPH_DIALECT.cypher_fn_for_field(fi) is None


class TestMemgraphDialectFulltextCall:
    def test_procedure_name(self) -> None:
        result = _MEMGRAPH_DIALECT.fulltext_call("Post", "n", "query")
        assert "text_search.search_all" in result

    def test_index_name_is_label(self) -> None:
        result = _MEMGRAPH_DIALECT.fulltext_call("Article", "n", "q")
        assert "'Article'" in result

    def test_query_param_substituted(self) -> None:
        result = _MEMGRAPH_DIALECT.fulltext_call("Post", "n", "my_query")
        assert "$my_query" in result

    def test_yield_aliases_node(self) -> None:
        result = _MEMGRAPH_DIALECT.fulltext_call("Post", "p", "q")
        assert "YIELD node AS p" in result

    def test_yield_includes_score(self) -> None:
        result = _MEMGRAPH_DIALECT.fulltext_call("Post", "p", "q")
        assert "score" in result


class TestMemgraphDialectVectorKnn:
    def test_start_uses_vector_search_procedure(self) -> None:
        result = _MEMGRAPH_DIALECT.vector_knn_start(
            "n", "Article", "Article", "embedding"
        )
        assert "vector_search.search" in result

    def test_start_index_name_is_type_underscore_field(self) -> None:
        result = _MEMGRAPH_DIALECT.vector_knn_start(
            "n", "Article", "Article", "embedding"
        )
        assert "'Article_embedding'" in result

    def test_start_yields_node_aliased(self) -> None:
        result = _MEMGRAPH_DIALECT.vector_knn_start(
            "n", "Article", "Article", "embedding"
        )
        assert "YIELD node AS n" in result

    def test_start_yields_distance_and_similarity(self) -> None:
        result = _MEMGRAPH_DIALECT.vector_knn_start(
            "n", "Article", "Article", "embedding"
        )
        assert "distance" in result
        assert "similarity" in result

    def test_start_includes_knn_params(self) -> None:
        result = _MEMGRAPH_DIALECT.vector_knn_start(
            "n", "Article", "Article", "embedding"
        )
        assert "$__knn_k" in result
        assert "$__knn_vec" in result

    def test_score_expr_maps_distance_to_score(self) -> None:
        result = _MEMGRAPH_DIALECT.vector_knn_score_expr("n", "embedding")
        assert "distance AS __score" == result

    def test_start_ignores_labels_str(self) -> None:
        r1 = _MEMGRAPH_DIALECT.vector_knn_start("n", "Article:Base", "Article", "emb")
        r2 = _MEMGRAPH_DIALECT.vector_knn_start("n", "Article", "Article", "emb")
        assert r1 == r2


class TestMemgraphDialectWrappers:
    def test_wrap_node_returns_bolt_node(self) -> None:
        raw = MagicMock()
        raw.id = 1
        raw.labels = frozenset(["Thing"])
        node = _MEMGRAPH_DIALECT.wrap_node(raw)
        assert isinstance(node, BoltNode)

    def test_wrap_edge_returns_bolt_edge(self) -> None:
        raw = MagicMock()
        edge = _MEMGRAPH_DIALECT.wrap_edge(raw)
        assert isinstance(edge, BoltEdge)


class TestCreateMemgraphDriver:
    def test_returns_bolt_driver(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_memgraph_driver(
                host="localhost",
                port=7687,
                database="memgraph",
                username="",
                password="",
            )
        assert isinstance(driver, BoltDriver)

    def test_dialect_is_memgraph(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_memgraph_driver(
                host="localhost",
                port=7687,
                database="memgraph",
                username="",
                password="",
            )
        assert isinstance(driver.dialect, MemgraphDialect)

    def test_default_encrypted_is_false(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_memgraph_driver(
                host="localhost",
                port=7687,
                database="memgraph",
                username="",
                password="",
            )
        assert driver.uri.startswith("bolt://")

    def test_encrypted_true_rewrites_uri(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_memgraph_driver(
                host="mg.example.com",
                port=7687,
                database="memgraph",
                username="admin",
                password="secret",
                encrypted=True,
            )
        assert driver.uri.startswith("bolt+s://")

    def test_create_driver_factory_dispatches_memgraph(self) -> None:
        with patch("runic.orm.driver.memgraph.create_memgraph_driver") as mock_factory:
            mock_factory.return_value = MagicMock(spec=BoltDriver)
            from runic.orm.driver.factory import create_driver

            create_driver(
                "memgraph",
                host="localhost",
                port=7687,
                database="memgraph",
                username="",
                password="",
            )
        mock_factory.assert_called_once()

    def test_dialect_singleton_is_reused(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            d1 = create_memgraph_driver("h", 7687, "db", "u", "p")
            d2 = create_memgraph_driver("h", 7687, "db", "u", "p")
        assert d1.dialect is d2.dialect
