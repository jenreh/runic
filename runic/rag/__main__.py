"""``python -m runic.rag`` entry point — delegates to the Typer CLI app."""

from __future__ import annotations

from runic.rag.cli import main

if __name__ == "__main__":
    main()
