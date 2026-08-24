"""Unit tests for NeptuneAnalyticsDialect."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runic.ogm.driver import CypherFeature, dialect_supports
from runic.ogm.driver.neptune_analytics import (
    _NEPTUNE_ANALYTICS_DIALECT,
    NeptuneAnalyticsEdge,
    NeptuneAnalyticsNode,
)


class TestNeptuneAnalyticsDialectFeatures:
    def test_only_fulltext_unsupported(self) -> None:
        assert _NEPTUNE_ANALYTICS_DIALECT.unsupported_features == frozenset(
            {CypherFeature.FULLTEXT_SEARCH}
        )

    def test_vector_and_procedures_supported(self) -> None:
        assert dialect_supports(_NEPTUNE_ANALYTICS_DIALECT, CypherFeature.VECTOR_SEARCH)
        assert dialect_supports(
            _NEPTUNE_ANALYTICS_DIALECT, CypherFeature.PROCEDURE_CALL
        )


class TestNeptuneAnalyticsDialectGeneratedIdWhere:
    def test_no_integer_cast(self) -> None:
        result = _NEPTUNE_ANALYTICS_DIALECT.generated_id_where("n", "pk")
        assert result == "WHERE id(n) = $pk"
        assert "toInteger" not in result


class TestNeptuneAnalyticsDialectVectorKnn:
    def test_vector_knn_call_uses_topk_by_embedding(self) -> None:
        cypher = _NEPTUNE_ANALYTICS_DIALECT.vector_knn_call(
            "n", "Article", "embedding", "$__knn_k", "$__knn_vec"
        )
        assert "neptune.algo.vectors.topK.byEmbedding" in cypher
        assert "embedding: $__knn_vec" in cypher
        assert "topK: $__knn_k" in cypher
        assert "vertexFilter: {equals: {property: '~label', value: 'Article'}}" in (
            cypher
        )
        assert "YIELD node AS n, score" in cypher

    def test_vector_knn_start_binds_default_params(self) -> None:
        cypher = _NEPTUNE_ANALYTICS_DIALECT.vector_knn_start(
            "n", ":Article", "Article", "embedding"
        )
        assert "$__knn_vec" in cypher
        assert "$__knn_k" in cypher
        assert "value: 'Article'" in cypher

    def test_score_is_distance_lower_is_closer(self) -> None:
        assert _NEPTUNE_ANALYTICS_DIALECT.vector_score_expr() == "score"
        assert (
            _NEPTUNE_ANALYTICS_DIALECT.vector_knn_score_expr("n", "embedding")
            == "score AS __score"
        )

    def test_yield_omits_noop_rename(self) -> None:
        cypher = _NEPTUNE_ANALYTICS_DIALECT.vector_knn_call(
            "node", "Article", "embedding", "$k", "$v"
        )
        assert "YIELD node, score" in cypher
        assert "node AS node" not in cypher


class TestNeptuneAnalyticsDialectFulltext:
    def test_fulltext_call_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="Neptune Analytics"):
            _NEPTUNE_ANALYTICS_DIALECT.fulltext_call("Label", "n", "q")

    def test_fulltext_yields_score_false(self) -> None:
        assert _NEPTUNE_ANALYTICS_DIALECT.fulltext_yields_score() is False


class TestNeptuneAnalyticsDialectCypherFnForField:
    def test_returns_none_always(self) -> None:
        fi = MagicMock()
        assert _NEPTUNE_ANALYTICS_DIALECT.cypher_fn_for_field(fi) is None


class TestNeptuneAnalyticsWrappers:
    def test_wrap_node(self) -> None:
        raw = {
            "~id": "abc",
            "~entityType": "node",
            "~labels": ["User", "Admin"],
            "~properties": {"name": "Ada"},
        }
        node = _NEPTUNE_ANALYTICS_DIALECT.wrap_node(raw)
        assert isinstance(node, NeptuneAnalyticsNode)
        assert node.element_id == "abc"
        assert node.labels == ["User", "Admin"]
        assert node.properties == {"name": "Ada"}

    def test_wrap_node_defaults(self) -> None:
        node = NeptuneAnalyticsNode({})
        assert node.element_id == ""
        assert node.labels == []
        assert node.properties == {}

    def test_wrap_edge(self) -> None:
        raw = {
            "~id": "e1",
            "~entityType": "relationship",
            "~type": "KNOWS",
            "~properties": {"since": 2020},
        }
        edge = _NEPTUNE_ANALYTICS_DIALECT.wrap_edge(raw)
        assert isinstance(edge, NeptuneAnalyticsEdge)
        assert edge.type == "KNOWS"
        assert edge.properties == {"since": 2020}
