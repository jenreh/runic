"""Unit tests for Neo4jDialect and create_neo4j_driver."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from runic.orm.driver.bolt import BoltDriver, BoltEdge, BoltNode
from runic.orm.driver.neo4j import _NEO4J_DIALECT, Neo4jDialect, create_neo4j_driver


class TestNeo4jDialectGeneratedIdWhere:
    def test_basic(self) -> None:
        assert _NEO4J_DIALECT.generated_id_where("n", "pk") == "WHERE id(n) = $pk"

    def test_alias_and_param_are_substituted(self) -> None:
        result = _NEO4J_DIALECT.generated_id_where("node", "node_id")
        assert "node" in result
        assert "$node_id" in result


class TestNeo4jDialectCypherFnForField:
    def test_returns_none_always(self) -> None:
        fi = MagicMock()
        assert _NEO4J_DIALECT.cypher_fn_for_field(fi) is None

    def test_ignores_interned_field(self) -> None:
        fi = MagicMock()
        fi.field.interned = True
        assert _NEO4J_DIALECT.cypher_fn_for_field(fi) is None


class TestNeo4jDialectFulltextCall:
    def test_procedure_name(self) -> None:
        result = _NEO4J_DIALECT.fulltext_call("Post", "n", "query")
        assert "db.index.fulltext.queryNodes" in result

    def test_index_name_is_label(self) -> None:
        result = _NEO4J_DIALECT.fulltext_call("Article", "n", "q")
        assert "'Article'" in result

    def test_query_param_substituted(self) -> None:
        result = _NEO4J_DIALECT.fulltext_call("Post", "n", "my_query")
        assert "$my_query" in result

    def test_yield_aliases_node(self) -> None:
        result = _NEO4J_DIALECT.fulltext_call("Post", "p", "q")
        assert "YIELD node AS p" in result

    def test_yield_includes_score(self) -> None:
        result = _NEO4J_DIALECT.fulltext_call("Post", "p", "q")
        assert "score" in result


class TestNeo4jDialectVectorKnn:
    def test_start_uses_vector_procedure(self) -> None:
        result = _NEO4J_DIALECT.vector_knn_start("n", "Article", "Article", "embedding")
        assert "db.index.vector.queryNodes" in result

    def test_start_index_name_is_type_underscore_field(self) -> None:
        result = _NEO4J_DIALECT.vector_knn_start("n", "Article", "Article", "embedding")
        assert "'Article_embedding'" in result

    def test_start_yields_node_aliased(self) -> None:
        result = _NEO4J_DIALECT.vector_knn_start("n", "Article", "Article", "embedding")
        assert "YIELD node AS n" in result

    def test_start_yields_score(self) -> None:
        result = _NEO4J_DIALECT.vector_knn_start("n", "Article", "Article", "embedding")
        assert "score" in result

    def test_start_includes_knn_params(self) -> None:
        result = _NEO4J_DIALECT.vector_knn_start("n", "Article", "Article", "embedding")
        assert "$__knn_k" in result
        assert "$__knn_vec" in result

    def test_score_expr_inverts_similarity_to_distance(self) -> None:
        result = _NEO4J_DIALECT.vector_knn_score_expr("n", "embedding")
        # Must map Neo4j cosine similarity (1=best) to distance (0=best)
        assert "1.0 - score" in result
        assert "__score" in result

    def test_start_ignores_labels_str(self) -> None:
        # labels_str arg is unused — the index name comes from type_name + field_name
        r1 = _NEO4J_DIALECT.vector_knn_start("n", "Article:Base", "Article", "emb")
        r2 = _NEO4J_DIALECT.vector_knn_start("n", "Article", "Article", "emb")
        assert r1 == r2


class TestNeo4jDialectWrappers:
    def test_wrap_node_returns_bolt_node(self) -> None:
        raw = MagicMock()
        raw.id = 42
        raw.labels = frozenset(["Person"])
        node = _NEO4J_DIALECT.wrap_node(raw)
        assert isinstance(node, BoltNode)

    def test_wrap_edge_returns_bolt_edge(self) -> None:
        raw = MagicMock()
        node = _NEO4J_DIALECT.wrap_edge(raw)
        assert isinstance(node, BoltEdge)


class TestCreateNeo4jDriver:
    def test_returns_bolt_driver(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_neo4j_driver(
                host="localhost",
                port=7687,
                database="neo4j",
                username="neo4j",
                password="secret",
            )
        assert isinstance(driver, BoltDriver)

    def test_dialect_is_neo4j(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_neo4j_driver(
                host="localhost",
                port=7687,
                database="neo4j",
                username="neo4j",
                password="secret",
            )
        assert isinstance(driver.dialect, Neo4jDialect)

    def test_encrypted_true_rewrites_uri_to_bolt_plus_s(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_neo4j_driver(
                host="db.example.com",
                port=7687,
                database="neo4j",
                username="neo4j",
                password="secret",
                encrypted=True,
            )
        assert driver.uri.startswith("bolt+s://")

    def test_encrypted_false_keeps_bolt_scheme(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            driver = create_neo4j_driver(
                host="localhost",
                port=7687,
                database="neo4j",
                username="neo4j",
                password="secret",
                encrypted=False,
            )
        assert driver.uri.startswith("bolt://")

    def test_create_driver_factory_dispatches_neo4j(self) -> None:
        with patch("runic.orm.driver.neo4j.create_neo4j_driver") as mock_factory:
            mock_factory.return_value = MagicMock(spec=BoltDriver)
            from runic.orm.driver.factory import create_driver

            create_driver(
                "neo4j",
                host="localhost",
                port=7687,
                database="neo4j",
                username="neo4j",
                password="secret",
            )
        mock_factory.assert_called_once()

    def test_dialect_singleton_is_reused(self) -> None:
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            d1 = create_neo4j_driver("h", 7687, "db", "u", "p")
            d2 = create_neo4j_driver("h", 7687, "db", "u", "p")
        assert d1.dialect is d2.dialect
