import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runic.migrate.script import (
    AmbiguousRevision,
    Revision,
    RevisionNotFound,
    ScriptDirectory,
)


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


def test_iterate_revisions_downgrade_partial_target(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions("bbbbbbbbbbbb", "aaaa")
    assert [r.revision for r in revs] == ["bbbbbbbbbbbb"]


def test_iterate_revisions_upgrade_partial_target(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions(None, "bbbb")
    assert [r.revision for r in revs] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]


def test_topological_upgrade_path_partial_target(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.topological_upgrade_path(None, "bbbb")
    assert [r.revision for r in revs] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]


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


def test_create_round_trip_message_and_date(tmp_versions: Path) -> None:
    """Template-generated revisions must load back with correct message and create_date."""
    from datetime import UTC, datetime, timedelta

    sd = ScriptDirectory.load(tmp_versions)
    before = datetime.now(UTC)
    path = sd.create(
        "my migration msg", head="bbbbbbbbbbbb", script_location=tmp_versions
    )
    after = datetime.now(UTC) + timedelta(seconds=1)

    # Reload the ScriptDirectory to pick up the new file
    sd2 = ScriptDirectory.load(tmp_versions)
    rev_id = path.stem.split("_")[0]
    rev = sd2.get_revision(rev_id)

    assert rev.message == "my migration msg"
    assert before <= rev.create_date <= after


def test_create_truncate_slug_length(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    path = sd.create(
        "a very long message that exceeds forty characters easily",
        head="bbbbbbbbbbbb",
        script_location=tmp_versions,
        truncate_slug_length=10,
    )
    # stem is "<rev_id>_<slug>"; slug must be ≤ 10 chars
    slug_part = path.stem.split("_", 1)[1]
    assert len(slug_part) <= 10


def test_create_file_template_rev_and_slug(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    path = sd.create(
        "add users",
        head="bbbbbbbbbbbb",
        script_location=tmp_versions,
        rev_id="abc123",
        file_template="migration_%(rev)s_%(slug)s",
    )
    assert path.name == "migration_abc123_add_users.py"
    assert path.exists()


def test_create_file_template_date_tokens(tmp_versions: Path) -> None:
    import re
    from datetime import UTC, datetime

    sd = ScriptDirectory.load(tmp_versions)
    before = datetime.now(UTC)
    path = sd.create(
        "init schema",
        head="bbbbbbbbbbbb",
        script_location=tmp_versions,
        file_template="%(year).4d_%(month).2d_%(day).2d-%(rev)s_%(slug)s",
    )
    after = datetime.now(UTC)

    assert re.match(r"^\d{4}_\d{2}_\d{2}-[0-9a-f]+_\w+\.py$", path.name)
    # year in filename must match the year the test ran
    year_in_name = int(path.name[:4])
    assert before.year <= year_in_name <= after.year


def test_create_file_template_month_zero_padded(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    path = sd.create(
        "fix",
        head="bbbbbbbbbbbb",
        script_location=tmp_versions,
        rev_id="deadbeef1234",
        file_template="%(year).4d%(month).2d%(day).2d-%(rev)s_%(slug)s",
    )
    # month portion (chars 4-5) must be exactly 2 digits
    month_str = path.name[4:6]
    assert len(month_str) == 2
    assert month_str.isdigit()
