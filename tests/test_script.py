import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runic.script import AmbiguousRevision, Revision, RevisionNotFound, ScriptDirectory


@pytest.fixture
def tmp_versions(tmp_path: Path) -> Path:
    versions = tmp_path / "versions"
    versions.mkdir()

    rev1 = "aaaaaaaaaaaa"
    rev2 = "bbbbbbbbbbbb"

    (versions / f"{rev1}_first.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev1!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "first migration"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )

    (versions / f"{rev2}_second.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev2!r}
            down_revision = {rev1!r}
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "second migration"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )

    return tmp_path


def test_load_finds_both_revisions(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    assert len(sd._revisions) == 2


def test_get_revision_by_full_id(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    rev = sd.get_revision("aaaaaaaaaaaa")
    assert rev.revision == "aaaaaaaaaaaa"


def test_get_revision_by_prefix(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    rev = sd.get_revision("aaaa")
    assert rev.revision == "aaaaaaaaaaaa"


def test_ambiguous_prefix_raises(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    extra = Revision(
        revision="aaaa11111111",
        down_revision="bbbbbbbbbbbb",
        branch_labels=[],
        depends_on=[],
        irreversible=False,
        snapshot=False,
        message="extra",
        create_date=datetime(2026, 1, 3, tzinfo=UTC),
        path=tmp_versions / "versions" / "aaaa11111111_extra.py",
    )
    sd._revisions["aaaa11111111"] = extra
    with pytest.raises(AmbiguousRevision):
        sd.get_revision("aaaa")


def test_unknown_revision_raises(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    with pytest.raises(RevisionNotFound):
        sd.get_revision("zzzzzzzzzzzz")


def test_iterate_revisions_upgrade_order(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions(None, "bbbbbbbbbbbb")
    assert [r.revision for r in revs] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]


def test_iterate_revisions_upgrade_from_mid(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions("aaaaaaaaaaaa", "bbbbbbbbbbbb")
    assert [r.revision for r in revs] == ["bbbbbbbbbbbb"]


def test_iterate_revisions_downgrade_order(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions("bbbbbbbbbbbb", "aaaaaaaaaaaa")
    assert [r.revision for r in revs] == ["bbbbbbbbbbbb"]


def test_generate_revision_id_length() -> None:
    rev_id = ScriptDirectory.generate_revision_id()
    assert len(rev_id) == 12
    assert rev_id == rev_id.lower()
    assert all(c in "0123456789abcdef" for c in rev_id)


def test_create_writes_file(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    path = sd.create("add index", head="bbbbbbbbbbbb", script_location=tmp_versions)
    assert path.exists()
    content = path.read_text()
    assert "add index" in content
    assert "down_revision = 'bbbbbbbbbbbb'" in content
