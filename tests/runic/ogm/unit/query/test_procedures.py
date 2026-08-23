"""Unit tests for procedure calls, search scores, and runtime index DDL."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.ogm import alias, fulltext_search, param, score, select, var
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.driver.age import AGEDialect
from runic.ogm.driver.arcadedb import ArcadeDBDialect
from runic.ogm.driver.falkordb import FalkorDBDialect
from runic.ogm.driver.memgraph import MemgraphDialect
from runic.ogm.driver.neo4j import Neo4jDialect
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.query.specialised import FulltextQueryBuilder, VectorQueryBuilder
from tests.runic.ogm.catalog_models import Message

_real_meta.finalize()

_M = alias(Message, "m")


def _mock_session(dialect: Any = None) -> Any:
    mapper = Mapper(_real_meta, dialect) if dialect else Mapper(_real_meta)
    sess = MagicMock()
    sess._mapper = mapper
    sess.mapper = mapper
    sess.register_or_get = lambda e: e
    return sess


def _build(stmt: Any, dialect: Any = None) -> tuple[str, dict[str, Any]]:
    with stmt._bound_to(_mock_session(dialect)) as bound:
        return bound.build()


# ---------------------------------------------------------------------------
# call()
# ---------------------------------------------------------------------------


class TestCall:
    def test_emits_a_call_with_yields(self) -> None:
        stmt = select(_M).call(
            "db.idx.vector.queryNodes",
            "Message",
            "embedding",
            param("k"),
            _M.embedding,
            yields=["node", "score"],
        )
        cypher, _ = _build(stmt)
        assert (
            "CALL db.idx.vector.queryNodes('Message', 'embedding', $k, m.embedding) "
            "YIELD node, score" in cypher
        )

    def test_a_string_argument_is_a_literal_not_a_parameter(self) -> None:
        """An index name comes from the model, not the caller."""
        cypher, params = _build(
            select(Message).call("some.proc", "Message", yields=["node"])
        )
        assert "some.proc('Message')" in cypher
        assert params == {}

    def test_a_plain_value_is_bound(self) -> None:
        cypher, params = _build(select(Message).call("some.proc", 42))
        assert "some.proc($p0)" in cypher
        assert params == {"p0": 42}

    def test_procedure_name_segments_are_validated(self) -> None:
        with pytest.raises(ValueError, match="procedure name"):
            _build(select(Message).call("db.idx; DROP", yields=["node"]))

    def test_correlated_call_follows_the_match(self) -> None:
        stmt = (
            select(_M)
            .where(Message.embedding_model == param("model"))  # ty: ignore[invalid-argument-type]
            .call("p.q", _M.embedding, yields=["node"])
        )
        cypher, _ = _build(stmt)
        assert cypher.index("MATCH (m:Message)") < cypher.index("CALL p.q")
        assert cypher.index("WHERE") < cypher.index("CALL p.q")

    def test_refused_where_procedures_are_unavailable(self) -> None:
        stmt = select(Message).call("db.idx.vector.queryNodes", yields=["node"])
        for dialect in (AGEDialect(), ArcadeDBDialect()):
            with pytest.raises(NotImplementedError, match="CALL"):
                _build(stmt, dialect)

    def test_var_references_a_yielded_name(self) -> None:
        stmt = (
            select(_M)
            .call("p.q", yields=["node", "score"])
            .where(var("score") <= param("max_distance"))
        )
        cypher, _ = _build(stmt)
        assert "score <= $max_distance" in cypher

    def test_var_is_validated(self) -> None:
        with pytest.raises(ValueError, match="variable"):
            var("score) DETACH DELETE m //")


# ---------------------------------------------------------------------------
# Vector search
# ---------------------------------------------------------------------------


class TestVectorSearch:
    def test_every_backend_uses_its_index_procedure(self) -> None:
        expected = {
            FalkorDBDialect: "db.idx.vector.queryNodes",
            Neo4jDialect: "db.index.vector.queryNodes",
            MemgraphDialect: "vector_search.search",
            ArcadeDBDialect: "vector.neighbors",
        }
        for dialect_cls, procedure in expected.items():
            stmt = VectorQueryBuilder(
                None,
                Message,
                field=Message.embedding,  # ty: ignore[invalid-argument-type]
                vector=param("vector"),
                k=param("k"),
            )
            cypher, _ = _build(stmt, dialect_cls())
            assert procedure in cypher, dialect_cls.__name__

    def test_age_refuses_vector_search(self) -> None:
        stmt = VectorQueryBuilder(
            None,
            Message,
            field=Message.embedding,  # ty: ignore[invalid-argument-type]
            vector=param("v"),
            k=param("k"),
        )
        with pytest.raises(NotImplementedError, match="vector search"):
            _build(stmt, AGEDialect())

    def test_score_is_a_distance_on_every_backend(self) -> None:
        """Lower is closer, whatever convention the backend itself uses."""
        for dialect in (FalkorDBDialect(), Neo4jDialect(), MemgraphDialect()):
            stmt = VectorQueryBuilder(
                None,
                Message,
                field=Message.embedding,  # ty: ignore[invalid-argument-type]
                vector=param("v"),
                k=param("k"),
            )
            cypher, _ = _build(stmt, dialect)
            assert "AS __score" in cypher
            assert "ORDER BY __score ASC" in cypher

    def test_neo4j_similarity_is_inverted_to_a_distance(self) -> None:
        stmt = VectorQueryBuilder(
            None,
            Message,
            field=Message.embedding,  # ty: ignore[invalid-argument-type]
            vector=param("v"),
            k=param("k"),
        )
        cypher, _ = _build(stmt, Neo4jDialect())
        assert "(1.0 - score) AS __score" in cypher

    def test_search_width_is_separate_from_the_row_limit(self) -> None:
        stmt = VectorQueryBuilder(
            None,
            Message,
            field=Message.embedding,  # ty: ignore[invalid-argument-type]
            vector=param("v"),
            k=param("k"),
        ).limit(param("limit"))
        cypher, _ = _build(stmt)
        assert "$k" in cypher
        assert cypher.endswith("LIMIT $limit")
        assert stmt.parameter_names() == ("k", "limit", "v")

    def test_score_can_be_projected(self) -> None:
        stmt = VectorQueryBuilder(
            None,
            Message,
            field=Message.embedding,  # ty: ignore[invalid-argument-type]
            vector=param("v"),
            k=param("k"),
        ).project(Message.id, score().as_("distance"))
        cypher, _ = _build(stmt)
        assert "__score AS distance" in cypher

    def test_a_plain_value_is_bound_under_a_reserved_name(self) -> None:
        stmt = VectorQueryBuilder(
            None,
            Message,
            field=Message.embedding,  # ty: ignore[invalid-argument-type]
            vector=[0.1, 0.2],
            k=5,
        )
        _, params = _build(stmt)
        assert params == {"__knn_vec": [0.1, 0.2], "__knn_k": 5}


# ---------------------------------------------------------------------------
# Fulltext search
# ---------------------------------------------------------------------------


class TestFulltextSearch:
    def test_score_is_bound_for_projection(self) -> None:
        stmt = FulltextQueryBuilder(None, Message, query=param("text")).project(
            Message.id,
            score().as_("relevance"),
        )
        cypher, _ = _build(stmt)
        assert "score AS __score" in cypher
        assert "__score AS relevance" in cypher

    def test_a_self_alias_is_not_emitted(self) -> None:
        """FalkorDB rejects ``YIELD node AS node`` with a misleading message."""
        stmt = fulltext_search(alias(Message, "node"), query=param("text"))
        cypher, _ = _build(stmt)
        assert "YIELD node, score" in cypher
        assert "YIELD node AS node" not in cypher

    def test_a_renamed_yield_is_emitted(self) -> None:
        stmt = FulltextQueryBuilder(None, Message, query=param("text"))
        cypher, _ = _build(stmt)
        assert "YIELD node AS n, score" in cypher

    def test_refused_where_fulltext_is_unavailable(self) -> None:
        stmt = FulltextQueryBuilder(None, Message, query=param("text"))
        for dialect in (AGEDialect(), ArcadeDBDialect()):
            with pytest.raises(NotImplementedError, match="fulltext"):
                _build(stmt, dialect)


# ---------------------------------------------------------------------------
# Runtime index DDL
# ---------------------------------------------------------------------------


class TestIndexOperations:
    def test_resolves_a_model_to_its_label_and_property(self) -> None:
        from runic.ogm.schema.runtime_index import IndexOperations

        adapter = MagicMock()
        IndexOperations(adapter).create_vector_index(
            Message,
            Message.embedding,  # ty: ignore[invalid-argument-type]
            dimension=768,
        )
        adapter.create_vector_index.assert_called_once_with(
            "Message", "embedding", 768, "cosine"
        )

    def test_drop_delegates_to_the_adapter(self) -> None:
        from runic.ogm.schema.runtime_index import IndexOperations

        adapter = MagicMock()
        IndexOperations(adapter).drop_vector_index(Message, Message.embedding)  # ty: ignore[invalid-argument-type]
        adapter.drop_vector_index.assert_called_once_with("Message", "embedding")

    def test_resize_drops_before_creating(self) -> None:
        """A graph between the two answers every search with a driver error."""
        from runic.ogm.schema.runtime_index import IndexOperations

        adapter = MagicMock()
        IndexOperations(adapter).resize_vector_index(
            Message,
            Message.embedding,  # ty: ignore[invalid-argument-type]
            dimension=1536,
        )
        assert adapter.method_calls[0][0] == "drop_vector_index"
        assert adapter.method_calls[1][0] == "create_vector_index"

    def test_resize_tolerates_a_missing_index(self) -> None:
        from runic.ogm.schema.runtime_index import IndexOperations

        adapter = MagicMock()
        adapter.drop_vector_index.side_effect = RuntimeError("no such index")
        IndexOperations(adapter).resize_vector_index(
            Message,
            Message.embedding,  # ty: ignore[invalid-argument-type]
            dimension=4,
        )
        adapter.create_vector_index.assert_called_once()

    def test_an_unregistered_class_is_rejected(self) -> None:
        from runic.ogm.schema.runtime_index import IndexOperations

        class NotAModel:
            pass

        with pytest.raises(ValueError, match="not a registered Node"):
            IndexOperations(MagicMock()).drop_vector_index(
                NotAModel,
                Message.embedding,  # ty: ignore[invalid-argument-type]
            )

    def test_from_driver_explains_what_it_cannot_do(self) -> None:
        from runic.ogm.schema.runtime_index import IndexOperations

        with pytest.raises(NotImplementedError, match="create_adapter"):
            IndexOperations.from_driver(object())
