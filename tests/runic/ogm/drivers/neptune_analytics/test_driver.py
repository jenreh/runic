"""Unit tests for NeptuneAnalyticsDriver against a stubbed boto3 client."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import pytest

from runic.ogm.core.descriptors import Field
from runic.ogm.core.metadata import metadata
from runic.ogm.core.models import Node
from runic.ogm.core.types import Vector
from runic.ogm.driver import TransactionalGraphDriver
from runic.ogm.driver.neptune_analytics import (
    _NEPTUNE_ANALYTICS_DIALECT,
    NeptuneAnalyticsDriver,
    NeptuneAnalyticsResult,
    _jsonable_params,
    _serialize_param,
    create_neptune_analytics_driver,
)
from runic.ogm.mapper.mapper import Mapper


class _StubClient:
    """Minimal ``neptune-graph`` client double recording execute_query calls."""

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self.results = results or []
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def execute_query(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        body = json.dumps({"results": self.results}).encode()
        return {"payload": io.BytesIO(body)}

    def close(self) -> None:
        self.closed = True


def _node_doc(node_id: str = "n1", **props: Any) -> dict[str, Any]:
    return {
        "~id": node_id,
        "~entityType": "node",
        "~labels": ["User"],
        "~properties": props,
    }


class TestExecute:
    def test_sends_open_cypher_request(self) -> None:
        client = _StubClient()
        driver = NeptuneAnalyticsDriver("g-123", client=client)
        driver.execute("RETURN 1", {})
        call = client.calls[0]
        assert call["graphIdentifier"] == "g-123"
        assert call["queryString"] == "RETURN 1"
        assert call["language"] == "OPEN_CYPHER"
        assert "parameters" not in call

    def test_parameters_forwarded_as_dict(self) -> None:
        client = _StubClient()
        driver = NeptuneAnalyticsDriver("g-123", client=client)
        driver.execute("MATCH (n {name: $name}) RETURN n", {"name": "Ada"})
        assert client.calls[0]["parameters"] == {"name": "Ada"}

    def test_rows_and_columns_preserve_query_order(self) -> None:
        client = _StubClient(
            results=[
                {"n": _node_doc(name="Ada"), "score": 0.5},
                {"n": _node_doc("n2", name="Grace"), "score": 1.5},
            ]
        )
        driver = NeptuneAnalyticsDriver("g-123", client=client)
        result = driver.execute("...", {})
        assert result.columns == ["n", "score"]
        assert len(result.rows) == 2
        assert result.rows[0][1] == 0.5
        assert result.rows[1][0]["~id"] == "n2"

    def test_empty_results(self) -> None:
        driver = NeptuneAnalyticsDriver("g-123", client=_StubClient())
        result = driver.execute("MATCH (n) RETURN n", {})
        assert result.rows == []
        assert result.columns == []

    def test_result_satisfies_graph_result_shape(self) -> None:
        result = NeptuneAnalyticsResult([[1]], ["x"])
        assert result.rows == [[1]]
        assert result.columns == ["x"]

    def test_node_decodes_through_dialect(self) -> None:
        client = _StubClient(results=[{"n": _node_doc(name="Ada")}])
        driver = NeptuneAnalyticsDriver("g-123", client=client)
        result = driver.execute("MATCH (n) RETURN n", {})
        node = driver.dialect.wrap_node(result.rows[0][0])
        assert node.element_id == "n1"
        assert node.properties == {"name": "Ada"}


class TestParamSerialisation:
    def test_datetime_becomes_isoformat(self) -> None:
        stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert _jsonable_params({"at": stamp}) == {"at": stamp.isoformat()}

    def test_enum_becomes_value(self) -> None:
        class Color(Enum):
            RED = "red"

        assert _jsonable_params({"c": Color.RED}) == {"c": "red"}

    def test_unserialisable_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Neptune Analytics"):
            _serialize_param(object())


class TestUpsertVector:
    def test_emits_upsert_call(self) -> None:
        client = _StubClient(results=[{"success": True}])
        driver = NeptuneAnalyticsDriver("g-123", client=client)
        assert driver.upsert_vector("n1", [0.1, 0.2]) is True
        cypher = client.calls[0]["queryString"]
        assert "neptune.algo.vectors.upsert" in cypher
        assert client.calls[0]["parameters"] == {
            "__vec_id": "n1",
            "__vec_embedding": [0.1, 0.2],
        }

    def test_empty_result_reports_failure(self) -> None:
        driver = NeptuneAnalyticsDriver("g-123", client=_StubClient())
        assert driver.upsert_vector("n1", [0.1]) is False


class NaSyncDoc(Node, labels=["NaSyncDoc"]):
    """Module-level so the `Vector | None` string annotation resolves."""

    id: str = Field()
    embedding: Vector | None = Field(default=None)


class NaSyncPlain(Node, labels=["NaSyncPlain"]):
    id: str = Field()
    title: str = Field()


def _mapper(dialect: Any) -> Mapper:
    return Mapper(metadata, dialect=dialect)


class TestVectorAutoSync:
    """Session-managed Vector writes append the index upsert to the statement."""

    def test_create_appends_upsert_call(self) -> None:
        mapper = _mapper(_NEPTUNE_ANALYTICS_DIALECT)
        doc = NaSyncDoc(id="d1", embedding=Vector([0.1, 0.2]))
        cypher, params = mapper.build_create_query(doc)
        assert "CALL neptune.algo.vectors.upsert(n, $embedding)" in cypher
        assert cypher.rstrip().endswith("RETURN n")
        assert params["embedding"] == [0.1, 0.2]

    def test_update_appends_upsert_call(self) -> None:
        mapper = _mapper(_NEPTUNE_ANALYTICS_DIALECT)
        doc = NaSyncDoc(id="d1", embedding=Vector([0.3, 0.4]))
        cypher, _ = mapper.build_update_query(doc)
        assert "SET" in cypher
        assert "CALL neptune.algo.vectors.upsert(n, $embedding)" in cypher

    def test_none_embedding_no_upsert(self) -> None:
        mapper = _mapper(_NEPTUNE_ANALYTICS_DIALECT)
        cypher, _ = mapper.build_create_query(NaSyncDoc(id="d1", embedding=None))
        assert "vectors.upsert" not in cypher

    def test_no_vector_field_no_upsert(self) -> None:
        mapper = _mapper(_NEPTUNE_ANALYTICS_DIALECT)
        cypher, _ = mapper.build_create_query(NaSyncPlain(id="d1", title="t"))
        assert "vectors.upsert" not in cypher

    def test_sync_vectors_false_disables_upsert(self) -> None:
        driver = NeptuneAnalyticsDriver(
            "g-123", client=_StubClient(), sync_vectors=False
        )
        mapper = _mapper(driver.dialect)
        doc = NaSyncDoc(id="d1", embedding=Vector([0.1]))
        cypher, _ = mapper.build_create_query(doc)
        assert "vectors.upsert" not in cypher

    def test_other_dialects_unaffected(self) -> None:
        from runic.ogm.driver.neptune import _NEPTUNE_DIALECT

        mapper = _mapper(_NEPTUNE_DIALECT)
        doc = NaSyncDoc(id="d1", embedding=Vector([0.1]))
        cypher, _ = mapper.build_create_query(doc)
        assert "vectors.upsert" not in cypher


class TestDriverLifecycle:
    def test_not_transactional(self) -> None:
        driver = NeptuneAnalyticsDriver("g-123", client=_StubClient())
        assert not isinstance(driver, TransactionalGraphDriver)

    def test_close_closes_client(self) -> None:
        client = _StubClient()
        NeptuneAnalyticsDriver("g-123", client=client).close()
        assert client.closed is True

    def test_factory_and_dispatch(self) -> None:
        from runic.ogm.driver.factory import create_driver

        client = _StubClient()
        driver = create_neptune_analytics_driver("g-123", client=client)
        assert driver.graph_id == "g-123"
        dispatched = create_driver("neptune_analytics", graph_id="g-9", client=client)
        assert isinstance(dispatched, NeptuneAnalyticsDriver)
