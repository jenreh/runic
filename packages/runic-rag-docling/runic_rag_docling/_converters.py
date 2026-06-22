"""Converter strategy: local in-process Docling vs. remote ``docling-serve``.

The :class:`_DoclingConverter` protocol is the narrow seam the adapters depend
on (DIP/ISP): it turns a document path into either a ``DoclingDocument`` (for
fused chunking) or normalized Markdown (for parsing). Two strategies implement
it (concept §5.3, ADR-022):

* :class:`LocalDoclingConverter` runs Docling in-process. ``docling`` is heavy
  (torch) and optional, so it is imported lazily and memoized; a missing install
  raises a clear :class:`~runic.rag.RagError` with an install hint — the same
  shape as ``runic.rag.adapters.reranking.CrossEncoderReranker``.
* :class:`ServerDoclingConverter` talks to ``docling-serve`` over HTTP with
  ``httpx`` (also lazy/optional). Markdown comes straight from ``md_content``;
  the document is re-hydrated client-side from ``json_content`` via an injectable
  ``rehydrate`` callable whose default lazily imports ``docling-core`` — so unit
  tests inject a fake and never need ``docling-core`` installed.

No module-level import of ``docling``, ``docling-core``, or ``httpx`` lives here;
every heavy import is inside a method and guarded with an install hint.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from runic.rag import RagError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .settings import DoclingSettings

log = logging.getLogger(__name__)

__all__ = [
    "LocalDoclingConverter",
    "ServerDoclingConverter",
]

# docling-serve upload endpoint (concept §2.3). Pinned here so a server-API
# change is a one-line edit in this capsule.
_CONVERT_FILE_PATH = "/v1alpha/convert/file"

# Shared install hint for the server path (httpx + docling-core), referenced by
# both ServerDoclingConverter and the default rehydrate helper.
_SERVER_INSTALL_HINT = (
    "ServerDoclingConverter requires the 'httpx' and 'docling-core' packages. "
    "Install it with: uv add 'runic-rag-docling[server]'"
)


class _DoclingConverter(Protocol):  # noqa: PYI046 - injected seam, used via TYPE_CHECKING
    """Turns a document path into a ``DoclingDocument`` or into Markdown."""

    def document_from_path(self, path: str | Path) -> Any:
        """Return the parsed ``DoclingDocument`` for the file at *path*."""
        ...

    def markdown_from_path(self, path: str | Path) -> str:
        """Return the normalized Markdown for the file at *path*."""
        ...


class LocalDoclingConverter:
    """In-process converter backed by a memoized Docling ``DocumentConverter``.

    The ``DocumentConverter`` is built lazily on first use (so importing this
    module never pulls torch) and reused thereafter. ``settings.ocr`` is honored
    via ``PdfPipelineOptions``. A missing ``docling`` install raises
    :class:`~runic.rag.RagError` with :data:`_INSTALL_HINT`.
    """

    _INSTALL_HINT = (
        "LocalDoclingConverter requires the 'docling' package. "
        "Install it with: uv add 'runic-rag-docling[local]'"
    )

    def __init__(self, settings: DoclingSettings) -> None:
        self._settings = settings
        self._converter: Any | None = None

    def _load_converter(self) -> Any:
        """Lazily import docling and build the memoized DocumentConverter."""
        if self._converter is not None:
            return self._converter
        try:
            from docling.datamodel.base_models import (  # ty: ignore[unresolved-import]
                InputFormat,
            )
            from docling.datamodel.pipeline_options import (  # ty: ignore[unresolved-import]
                PdfPipelineOptions,
            )
            from docling.document_converter import (  # ty: ignore[unresolved-import]
                DocumentConverter,
                PdfFormatOption,
            )
        except ImportError as exc:  # pragma: no cover - exercised via fake patch
            raise RagError(self._INSTALL_HINT) from exc
        pdf_options = PdfPipelineOptions()
        pdf_options.do_ocr = self._settings.ocr
        log.debug("Building Docling DocumentConverter (ocr=%s)", self._settings.ocr)
        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)
            }
        )
        return self._converter

    def document_from_path(self, path: str | Path) -> Any:
        """Convert the file at *path* and return its ``DoclingDocument``."""
        converter = self._load_converter()
        return converter.convert(str(path)).document

    def markdown_from_path(self, path: str | Path) -> str:
        """Convert the file at *path* and export it to Markdown."""
        document = self.document_from_path(path)
        return document.export_to_markdown()


def _default_rehydrate(payload: dict[str, Any]) -> Any:
    """Re-hydrate a ``docling-core`` ``DoclingDocument`` from server JSON.

    Imported lazily so unit tests can inject a fake ``rehydrate`` and run
    without ``docling-core`` installed.
    """
    try:
        from docling_core.types.doc import (  # ty: ignore[unresolved-import]
            DoclingDocument,
        )
    except ImportError as exc:  # pragma: no cover - exercised via fake patch
        raise RagError(_SERVER_INSTALL_HINT) from exc
    return DoclingDocument.model_validate(payload)


class ServerDoclingConverter:
    """Converter that offloads parsing to a ``docling-serve`` HTTP service.

    The client stays light: ``httpx`` posts the file as a multipart upload and
    reads ``md_content`` (Markdown) and ``json_content`` (the lossless
    ``DoclingDocument`` JSON) back. Chunking stays client-side, so the document
    is re-hydrated from ``json_content`` via *rehydrate* (default
    :func:`_default_rehydrate`, which lazily imports ``docling-core``). The
    ``X-Api-Key`` header is sent only when ``settings.api_key`` is set.
    """

    _INSTALL_HINT = _SERVER_INSTALL_HINT

    def __init__(
        self,
        settings: DoclingSettings,
        *,
        rehydrate: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        if not settings.server_url:
            raise RagError("ServerDoclingConverter requires settings.server_url")
        self._settings = settings
        self._server_url = settings.server_url.rstrip("/")
        self._rehydrate = rehydrate or _default_rehydrate

    def _load_httpx(self) -> Any:
        """Lazily import httpx, raising a clear install hint when missing."""
        try:
            import httpx  # ty: ignore[unresolved-import]
        except ImportError as exc:  # pragma: no cover - exercised via fake patch
            raise RagError(self._INSTALL_HINT) from exc
        return httpx

    def _headers(self) -> dict[str, str]:
        """Return request headers, adding ``X-Api-Key`` only when configured."""
        if self._settings.api_key:
            return {"X-Api-Key": self._settings.api_key}
        return {}

    def _document_payload(self, path: str | Path) -> dict[str, Any]:
        """POST *path* as a multipart upload and return the response document."""
        httpx = self._load_httpx()
        url = self._server_url + _CONVERT_FILE_PATH
        file_path = Path(path)
        log.debug("Posting %s to docling-serve at %s", file_path.name, url)
        with file_path.open("rb") as handle:
            response = httpx.post(
                url,
                files={"files": (file_path.name, handle)},
                headers=self._headers(),
                timeout=self._settings.timeout,
            )
        response.raise_for_status()
        return response.json()["document"]

    def document_from_path(self, path: str | Path) -> Any:
        """Convert *path* via the server and re-hydrate a ``DoclingDocument``."""
        document = self._document_payload(path)
        return self._rehydrate(document["json_content"])

    def markdown_from_path(self, path: str | Path) -> str:
        """Convert *path* via the server and return its ``md_content``."""
        document = self._document_payload(path)
        return document["md_content"]
