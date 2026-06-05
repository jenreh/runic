from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def init(directory: Path, *, force: bool = False) -> None:
    """Scaffold a new runic migration environment on disk.

    Raises :exc:`FileExistsError` when *directory* exists and *force* is False.
    """
    if directory.exists() and not force:
        raise FileExistsError(
            f"{directory} already exists. Use force=True to overwrite."
        )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "versions").mkdir(exist_ok=True)
    (directory / "versions" / ".gitkeep").touch()

    templates_dir = Path(__file__).parent / "templates"
    (directory / "env.py").write_text((templates_dir / "env.py.mako").read_text())
    (directory / "script.py.mako").write_bytes(
        (templates_dir / "script.py.mako").read_bytes()
    )
    log.info("initialized runic environment at %s", directory)
