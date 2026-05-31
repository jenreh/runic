from pathlib import Path

from runic.checksum import file_checksum


def test_checksum_is_consistent(tmp_path: Path) -> None:
    f = tmp_path / "rev.py"
    f.write_text("revision = 'abc'\n")
    assert file_checksum(f) == file_checksum(f)


def test_checksum_differs_on_content_change(tmp_path: Path) -> None:
    f = tmp_path / "rev.py"
    f.write_text("revision = 'abc'\n")
    h1 = file_checksum(f)
    f.write_text("revision = 'xyz'\n")
    h2 = file_checksum(f)
    assert h1 != h2


def test_checksum_is_sha256_hex(tmp_path: Path) -> None:
    f = tmp_path / "rev.py"
    f.write_text("hello")
    digest = file_checksum(f)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
