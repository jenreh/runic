"""Typer CLI for runic.rag — a thin stub over :class:`~runic.rag.facade.GraphRAG`.

Three commands mirror the facade verbs:

* ``bootstrap`` — create the entity types and indexes.
* ``ingest <path> [--source]`` — ingest a document from disk.
* ``query <text> [--mode]`` — ask a question and print the cited answer.

Settings are read from the environment via :func:`~runic.rag.config.load_settings`,
so ``python -m runic.rag ...`` works with a local ``.env``. The CLI owns no
pipeline logic; it only parses arguments and forwards to the facade.
"""

from __future__ import annotations

import logging

import typer

from runic.rag.config import load_settings
from runic.rag.facade import GraphRAG

log = logging.getLogger(__name__)

__all__ = ["app", "main"]

app = typer.Typer(
    add_completion=False,
    help="runic.rag — Graph-RAG over the runic graph OGM.",
    no_args_is_help=True,
)


def _build() -> GraphRAG:
    """Construct a default-wired facade from environment settings."""
    return GraphRAG.with_defaults(settings=load_settings())


@app.command()
def bootstrap() -> None:
    """Create the knowledge-graph entity types and indexes (idempotent)."""
    _build().bootstrap_schema()
    typer.echo("Schema bootstrapped.")


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to a .txt, .md, or .pdf document."),
    source: str | None = typer.Option(
        None, "--source", help="Override the source tag (defaults to the path)."
    ),
) -> None:
    """Ingest a document at PATH into the knowledge graph."""
    rag = _build()
    if source is None:
        report = rag.ingest_document(path)
    else:
        from runic.rag.adapters import documents

        report = rag.ingest_text(documents.load_text(path), source=source)
    typer.echo(
        f"Ingested {path}: {report.chunks} chunks, {report.entities} entities, "
        f"{report.relations} relations, {report.mentions} mentions."
    )


@app.command()
def query(
    text: str = typer.Argument(..., help="The natural-language question."),
    mode: str = typer.Option(
        "auto", "--mode", help="Retrieval mode: auto, local, or hybrid."
    ),
) -> None:
    """Answer a question grounded in the knowledge graph."""
    answer = _build().query(text, mode=mode)
    typer.echo(answer.text)
    if answer.citations:
        typer.echo("\nCitations:")
        for citation in answer.citations:
            typer.echo(f"- [{citation.chunk_id}] {citation.source}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover - module CLI guard
    main()
