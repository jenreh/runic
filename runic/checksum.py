from __future__ import annotations

import hashlib
from pathlib import Path


def file_checksum(path: Path) -> str:
    """Return SHA-256 hex digest of a migration script file.

    Hashes the raw bytes of the file. Re-formatting a script after it has been
    applied will produce a checksum mismatch — review before stamping or use
    `runic stamp` to re-anchor.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()
