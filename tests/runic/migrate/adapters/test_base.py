"""Tests for shared _base helpers — _parse_kv_list and _encode_kv_list.

These were previously duplicated across test_neo4j_adapter.py,
test_memgraph_adapter.py, and test_age_adapter.py.
"""

from __future__ import annotations

from runic.migrate.adapters._base import _encode_kv_list, _parse_kv_list


class TestParseKvList:
    def test_basic(self) -> None:
        assert _parse_kv_list(["a:1", "b:2"]) == {"a": "1", "b": "2"}

    def test_empty_list(self) -> None:
        assert _parse_kv_list([]) == {}

    def test_none(self) -> None:
        assert _parse_kv_list(None) == {}

    def test_empty_item_skipped(self) -> None:
        assert _parse_kv_list(["", "x:9"]) == {"x": "9"}


class TestEncodeKvList:
    def test_basic(self) -> None:
        assert set(_encode_kv_list({"a": "1"})) == {"a:1"}

    def test_empty(self) -> None:
        assert _encode_kv_list({}) == []
