"""Unit tests for :class:`runic_rag_docling._converters.ServerDoclingConverter`.

A real ``docling-serve`` is stood up with the ``pytest-httpserver`` fixture, so
the only heavy dependency exercised is ``httpx`` (synced via the dev group);
``docling-core`` is never needed because the document re-hydration is performed
by an **injected** fake ``rehydrate`` callable. The suite proves the converter
posts the file as a multipart upload, sends ``X-Api-Key`` only when configured,
returns the served Markdown, and feeds the served JSON to the injected rehydrate.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from runic.rag import RagError
from werkzeug import Request, Response

from runic_rag_docling import DoclingSettings
from runic_rag_docling._converters import ServerDoclingConverter

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_httpserver import HTTPServer

_CONVERT_PATH = "/v1alpha/convert/file"
_MD = "# Served\n\nbody\n"
_JSON_CONTENT = {"schema_name": "DoclingDocument", "name": "served"}


class _Capture:
    """Records the multipart upload and headers the converter sent."""

    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def __call__(self, request: Request) -> Response:
        upload = request.files.get("files")
        self.received["filename"] = upload.filename if upload else None
        self.received["body"] = upload.read() if upload else None
        self.received["api_key"] = request.headers.get("X-Api-Key")
        payload = {"document": {"md_content": _MD, "json_content": _JSON_CONTENT}}
        return Response(json.dumps(payload), content_type="application/json")


def _pdf(tmp_path: Path) -> Path:
    """Write a tiny placeholder file to upload (content is opaque to the test)."""
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.4 fake bytes")
    return path


def _converter(
    httpserver: HTTPServer,
    *,
    api_key: str | None = None,
    rehydrate: Any = None,
) -> ServerDoclingConverter:
    """Build a ServerDoclingConverter pointed at the fake server."""
    settings = DoclingSettings(
        mode="server",
        server_url=httpserver.url_for("/"),
        api_key=api_key,
    )
    return ServerDoclingConverter(settings, rehydrate=rehydrate)


# ── markdown_from_path ───────────────────────────────────────────────────────


def test_markdown_from_path_posts_file_and_returns_md(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """The file is posted multipart and the served ``md_content`` is returned."""
    capture = _Capture()
    httpserver.expect_request(_CONVERT_PATH, method="POST").respond_with_handler(
        capture
    )
    pdf = _pdf(tmp_path)

    markdown = _converter(httpserver).markdown_from_path(pdf)

    assert markdown == _MD
    assert capture.received["filename"] == "paper.pdf"
    assert capture.received["body"] == b"%PDF-1.4 fake bytes"


def test_api_key_header_omitted_when_unset(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """No ``X-Api-Key`` header is sent when ``api_key`` is unset."""
    capture = _Capture()
    httpserver.expect_request(_CONVERT_PATH, method="POST").respond_with_handler(
        capture
    )

    _converter(httpserver).markdown_from_path(_pdf(tmp_path))

    assert capture.received["api_key"] is None


def test_api_key_header_sent_when_set(httpserver: HTTPServer, tmp_path: Path) -> None:
    """``X-Api-Key`` carries the configured key when ``api_key`` is set."""
    capture = _Capture()
    httpserver.expect_request(_CONVERT_PATH, method="POST").respond_with_handler(
        capture
    )

    _converter(httpserver, api_key="secret-key").markdown_from_path(_pdf(tmp_path))

    assert capture.received["api_key"] == "secret-key"


# ── document_from_path (injected rehydrate, no docling-core) ─────────────────


def test_document_from_path_feeds_json_to_injected_rehydrate(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """The served ``json_content`` is handed to *rehydrate* and propagated."""
    httpserver.expect_request(_CONVERT_PATH, method="POST").respond_with_json(
        {"document": {"md_content": _MD, "json_content": _JSON_CONTENT}}
    )
    seen: dict[str, Any] = {}
    sentinel = object()

    def fake_rehydrate(payload: dict[str, Any]) -> object:
        seen["payload"] = payload
        return sentinel

    document = _converter(httpserver, rehydrate=fake_rehydrate).document_from_path(
        _pdf(tmp_path)
    )

    # The injected callable received exactly the server's json_content...
    assert seen["payload"] == _JSON_CONTENT
    # ...and its return value is propagated unchanged (no docling-core needed).
    assert document is sentinel


# ── error surface ────────────────────────────────────────────────────────────


def test_server_error_raises_for_status(httpserver: HTTPServer, tmp_path: Path) -> None:
    """A non-2xx response surfaces as an httpx error (not a silent empty result)."""
    httpserver.expect_request(_CONVERT_PATH, method="POST").respond_with_data(
        "boom", status=500
    )
    import httpx

    with pytest.raises(httpx.HTTPStatusError):
        _converter(httpserver).markdown_from_path(_pdf(tmp_path))


def test_missing_server_url_raises_config_ragerror() -> None:
    """Constructing without a ``server_url`` is a clear RagError, not a crash."""
    with pytest.raises(RagError):
        ServerDoclingConverter(DoclingSettings(mode="server", server_url=None))
