"""Unit tests for AGEDialect, AGEDriver, and related helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest

from runic.ogm.driver.age import (
    _AGE_DIALECT,
    AGEDialect,
    AGEDriver,
    AGEEdge,
    AGENode,
    AGEResult,
    _AGEEdgeData,
    _AGEVertexData,
    _parse_agtype,
    _parse_return_columns,
    _serialize_param,
    _split_at_top_level_commas,
    create_age_driver,
)

# ---------------------------------------------------------------------------
# _parse_agtype
# ---------------------------------------------------------------------------


class TestParseAgtype:
    def test_plain_string(self) -> None:
        assert _parse_agtype('"hello"') == "hello"

    def test_plain_integer(self) -> None:
        assert _parse_agtype("42") == 42

    def test_plain_list(self) -> None:
        assert _parse_agtype("[1, 2, 3]") == [1, 2, 3]

    def test_plain_dict(self) -> None:
        assert _parse_agtype('{"a": 1}') == {"a": 1}

    def test_vertex_type_tag(self) -> None:
        raw = '{"id": 1, "label": "Person", "properties": {"name": "Alice"}}::vertex'
        result = _parse_agtype(raw)
        assert isinstance(result, _AGEVertexData)
        assert result.id == 1
        assert result.label == "Person"
        assert result.properties == {"name": "Alice"}

    def test_vertex_empty_properties(self) -> None:
        raw = '{"id": 2, "label": "Thing", "properties": null}::vertex'
        result = _parse_agtype(raw)
        assert isinstance(result, _AGEVertexData)
        assert result.properties == {}

    def test_edge_type_tag(self) -> None:
        raw = (
            '{"id": 5, "label": "KNOWS", "start_id": 1, "end_id": 2, '
            '"properties": {"since": 2020}}::edge'
        )
        result = _parse_agtype(raw)
        assert isinstance(result, _AGEEdgeData)
        assert result.id == 5
        assert result.label == "KNOWS"
        assert result.start_id == 1
        assert result.end_id == 2
        assert result.properties == {"since": 2020}

    def test_unknown_type_tag_returns_json_body(self) -> None:
        raw = '{"x": 99}::sometype'
        result = _parse_agtype(raw)
        assert result == {"x": 99}

    def test_whitespace_stripped(self) -> None:
        result = _parse_agtype("  42  ")
        assert result == 42


# ---------------------------------------------------------------------------
# _serialize_param
# ---------------------------------------------------------------------------


class TestSerializeParam:
    def test_datetime_to_iso(self) -> None:
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        assert _serialize_param(dt) == "2024-01-15T10:30:00+00:00"

    def test_enum_to_value(self) -> None:
        class Color(Enum):
            RED = "red"

        assert _serialize_param(Color.RED) == "red"

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Cannot serialise"):
            _serialize_param(object())


# ---------------------------------------------------------------------------
# _split_at_top_level_commas
# ---------------------------------------------------------------------------


class TestSplitAtTopLevelCommas:
    def test_simple(self) -> None:
        assert _split_at_top_level_commas("a, b, c") == ["a", " b", " c"]

    def test_nested_parens(self) -> None:
        result = _split_at_top_level_commas("count(n, m), n")
        assert result == ["count(n, m)", " n"]

    def test_single_item(self) -> None:
        assert _split_at_top_level_commas("n") == ["n"]

    def test_empty(self) -> None:
        assert _split_at_top_level_commas("") == []


# ---------------------------------------------------------------------------
# _parse_return_columns
# ---------------------------------------------------------------------------


class TestParseReturnColumns:
    def test_simple_identifier(self) -> None:
        # QueryBuilder emits RETURN on its own line
        assert _parse_return_columns("MATCH (n)\nRETURN n") == ["n"]

    def test_multiple_identifiers(self) -> None:
        result = _parse_return_columns("MATCH (n)-[r]->(m)\nRETURN n, r, m")
        assert result == ["n", "r", "m"]

    def test_property_access(self) -> None:
        result = _parse_return_columns("MATCH (n)\nRETURN n.name")
        assert result == ["name"]

    def test_explicit_as_alias(self) -> None:
        result = _parse_return_columns("MATCH (n)\nRETURN count(*) AS cnt")
        assert result == ["cnt"]

    def test_distinct_stripped(self) -> None:
        result = _parse_return_columns("MATCH (n)\nRETURN DISTINCT n")
        assert result == ["n"]

    def test_no_return_clause(self) -> None:
        assert _parse_return_columns("MATCH (n)") == ["result"]

    def test_score_alias(self) -> None:
        result = _parse_return_columns(
            "CALL db.index.vector.queryNodes('idx', 5, $v)\n"
            "YIELD node AS n, score\n"
            "RETURN n, (1.0 - score) AS __score"
        )
        assert "__score" in result
        assert "n" in result

    def test_fallback_positional_name(self) -> None:
        # expression that isn't a simple identifier or property or AS alias
        result = _parse_return_columns("MATCH (n)\nRETURN n + 1")
        assert result == ["col0"]


# ---------------------------------------------------------------------------
# AGENode / AGEEdge wrappers
# ---------------------------------------------------------------------------


class TestAGENode:
    def test_element_id(self) -> None:
        raw = _AGEVertexData(id=42, label="Person", properties={"name": "Alice"})
        node = AGENode(raw)
        assert node.element_id == 42

    def test_labels_single(self) -> None:
        raw = _AGEVertexData(id=1, label="Movie", properties={})
        node = AGENode(raw)
        assert node.labels == ["Movie"]

    def test_labels_from_labels_property(self) -> None:
        raw = _AGEVertexData(
            id=1, label="Location", properties={"_labels": ["Location", "Country"]}
        )
        node = AGENode(raw)
        assert node.labels == ["Location", "Country"]

    def test_labels_falls_back_when_not_list(self) -> None:
        raw = _AGEVertexData(id=1, label="X", properties={"_labels": "bad"})
        node = AGENode(raw)
        assert node.labels == ["X"]

    def test_properties(self) -> None:
        raw = _AGEVertexData(id=1, label="X", properties={"a": 1, "b": 2})
        node = AGENode(raw)
        assert node.properties == {"a": 1, "b": 2}

    def test_properties_returns_copy(self) -> None:
        raw = _AGEVertexData(id=1, label="X", properties={"a": 1})
        node = AGENode(raw)
        node.properties["a"] = 99
        assert raw.properties == {"a": 1}


class TestAGEEdge:
    def test_type(self) -> None:
        raw = _AGEEdgeData(id=5, label="KNOWS", start_id=1, end_id=2, properties={})
        edge = AGEEdge(raw)
        assert edge.type == "KNOWS"

    def test_properties(self) -> None:
        raw = _AGEEdgeData(id=5, label="X", start_id=1, end_id=2, properties={"w": 0.5})
        edge = AGEEdge(raw)
        assert edge.properties == {"w": 0.5}


# ---------------------------------------------------------------------------
# AGEResult
# ---------------------------------------------------------------------------


class TestAGEResult:
    def test_rows(self) -> None:
        r = AGEResult([[1, 2], [3, 4]], ["a", "b"])
        assert r.rows == [[1, 2], [3, 4]]

    def test_columns(self) -> None:
        r = AGEResult([], ["x", "y"])
        assert r.columns == ["x", "y"]


# ---------------------------------------------------------------------------
# AGEDialect
# ---------------------------------------------------------------------------


class TestAGEDialect:
    def test_generated_id_where(self) -> None:
        assert _AGE_DIALECT.generated_id_where("n", "pk") == "WHERE id(n) = $pk"

    def test_cypher_fn_for_field_always_none(self) -> None:
        fi = MagicMock()
        assert _AGE_DIALECT.cypher_fn_for_field(fi) is None

    def test_fulltext_call_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="Apache AGE"):
            _AGE_DIALECT.fulltext_call("Label", "n", "q")

    def test_vector_knn_start_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="Apache AGE"):
            _AGE_DIALECT.vector_knn_start("n", "L", "T", "f")

    def test_vector_knn_score_expr_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="Apache AGE"):
            _AGE_DIALECT.vector_knn_score_expr("n", "f")

    def test_wrap_node(self) -> None:
        raw = _AGEVertexData(id=1, label="X", properties={})
        node = _AGE_DIALECT.wrap_node(raw)
        assert isinstance(node, AGENode)

    def test_wrap_edge(self) -> None:
        raw = _AGEEdgeData(id=1, label="E", start_id=0, end_id=2, properties={})
        edge = _AGE_DIALECT.wrap_edge(raw)
        assert isinstance(edge, AGEEdge)

    def test_dialect_is_singleton(self) -> None:
        assert isinstance(_AGE_DIALECT, AGEDialect)

    def test_labels_clause_returns_primary_only(self) -> None:
        assert _AGE_DIALECT.labels_clause(["Location", "Country"]) == "Location"

    def test_labels_clause_single_label(self) -> None:
        assert _AGE_DIALECT.labels_clause(["Person"]) == "Person"

    def test_subtype_where_none_for_single_label(self) -> None:
        assert _AGE_DIALECT.subtype_where("n", ["Location"]) is None

    def test_subtype_where_condition_for_subtype(self) -> None:
        result = _AGE_DIALECT.subtype_where("n", ["Location", "Country"])
        assert result == '"Country" IN n._labels'

    def test_subtype_where_multiple_subtypes(self) -> None:
        result = _AGE_DIALECT.subtype_where("n", ["A", "B", "C"])
        assert result == '"B" IN n._labels AND "C" IN n._labels'

    def test_needs_labels_property_true(self) -> None:
        assert _AGE_DIALECT.needs_labels_property() is True


# ---------------------------------------------------------------------------
# AGEDriver
# ---------------------------------------------------------------------------


def _make_driver(graph_name: str = "test_graph") -> tuple[AGEDriver, MagicMock]:
    mock_conn = MagicMock()
    driver = AGEDriver(mock_conn, graph_name)
    return driver, mock_conn


class TestAGEDriver:
    def test_dialect_is_age(self) -> None:
        driver, _ = _make_driver()
        assert isinstance(driver.dialect, AGEDialect)

    def test_execute_no_params_builds_sql_without_agtype(self) -> None:
        driver, mock_conn = _make_driver("g")
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.description = []
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cur

        driver.execute("MATCH (n) RETURN n", {})

        sql_call = mock_cur.execute.call_args_list[0]
        sql = sql_call[0][0]
        assert "cypher('g'" in sql
        assert "%s::agtype" not in sql

    def test_execute_with_params_includes_agtype(self) -> None:
        driver, mock_conn = _make_driver("g")
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.description = []
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cur

        driver.execute("MATCH (n {id: $id}) RETURN n", {"id": "alice"})

        sql_call = mock_cur.execute.call_args_list[0]
        sql = sql_call[0][0]
        assert "%s::agtype" in sql

    def test_execute_returns_age_result(self) -> None:
        driver, mock_conn = _make_driver("g")
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        col = MagicMock()
        col.name = "n"
        mock_cur.description = [col]
        mock_cur.fetchall.return_value = [("node_data",)]
        mock_conn.cursor.return_value = mock_cur

        result = driver.execute("MATCH (n) RETURN n", {})

        assert isinstance(result, AGEResult)
        assert result.columns == ["n"]
        assert len(result.rows) == 1

    def test_execute_does_not_auto_commit(self) -> None:
        # commit() is the Session's responsibility, not execute()'s
        driver, mock_conn = _make_driver("g")
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.description = []
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cur

        driver.execute("MATCH (n)\nRETURN n", {})

        mock_conn.commit.assert_not_called()

    def test_close_closes_connection(self) -> None:
        driver, mock_conn = _make_driver()
        driver.close()
        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# create_age_driver
# ---------------------------------------------------------------------------


class TestCreateAgeDriver:
    def test_returns_age_driver(self) -> None:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.side_effect = [None, (1,)]
        mock_conn.cursor.return_value = mock_cur

        with patch("psycopg.connect", return_value=mock_conn):
            driver = create_age_driver(
                host="localhost",
                port=5432,
                database="postgres",
                graph="my_graph",
                username="postgres",
                password="secret",
            )

        assert isinstance(driver, AGEDriver)

    def test_dispatches_via_factory(self) -> None:
        with patch("runic.ogm.driver.age.create_age_driver") as mock_factory:
            mock_factory.return_value = MagicMock(spec=AGEDriver)
            from runic.ogm.driver.factory import create_driver

            create_driver(
                "age",
                host="localhost",
                port=5432,
                database="postgres",
                graph="my_graph",
                username="postgres",
                password="secret",
            )

        mock_factory.assert_called_once()
