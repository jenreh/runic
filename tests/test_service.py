"""SDK-level tests for RunicService — no CLI involved."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from runic.service import RunicService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scaffold_two_revisions(script_location: Path) -> tuple[str, str]:
    """Write two chained revision files and return (rev1, rev2)."""
    rev1 = "aaaaaaaaaaaa"
    rev2 = "bbbbbbbbbbbb"
    versions = script_location / "versions"
    versions.mkdir(parents=True, exist_ok=True)

    (versions / f"{rev1}_first.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev1!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "initial schema"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)

            def upgrade(op): pass
            def downgrade(op): pass
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
            message = "add email index"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)

            def upgrade(op): pass
            def downgrade(op): pass
        """)
    )
    return rev1, rev2


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_expected_files(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    RunicService.init(target)
    assert (target / "env.py").exists()
    assert (target / "script.py.mako").exists()
    assert (target / "versions").is_dir()
    assert (target / "versions" / ".gitkeep").exists()


def test_init_env_py_contains_falkordb_stub(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    RunicService.init(target)
    content = (target / "env.py").read_text()
    assert "FalkorDB" in content
    assert "context.configure" in content


def test_init_raises_if_exists_without_force(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    target.mkdir()
    with pytest.raises(FileExistsError):
        RunicService.init(target)


def test_init_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    target.mkdir()
    RunicService.init(target, force=True)
    assert (target / "env.py").exists()


# ---------------------------------------------------------------------------
# create_revision
# ---------------------------------------------------------------------------


def test_create_revision_returns_path(tmp_path: Path) -> None:
    RunicService.init(tmp_path / "runic")
    svc = RunicService(tmp_path / "runic")
    path = svc.create_revision("add email index")
    assert path.exists()
    assert "add email index" in path.read_text()


def test_create_revision_links_to_head(tmp_path: Path) -> None:
    RunicService.init(tmp_path / "runic")
    svc = RunicService(tmp_path / "runic")
    path1 = svc.create_revision("first")
    # reload so second revision sees first as head
    svc2 = RunicService(tmp_path / "runic")
    path2 = svc2.create_revision("second")
    assert path1.exists()
    assert path2.exists()
    content = path2.read_text()
    # down_revision of second must reference the first revision's id
    first_rev_id = path1.stem.split("_")[0]
    assert first_rev_id in content


def test_create_revision_accepts_custom_rev_id(tmp_path: Path) -> None:
    RunicService.init(tmp_path / "runic")
    svc = RunicService(tmp_path / "runic")
    path = svc.create_revision("custom", rev_id="deadbeef1234")
    assert "deadbeef1234" in path.name


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


def test_get_history_newest_first(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    history = svc.get_history()
    assert history[0].revision == "bbbbbbbbbbbb"
    assert history[1].revision == "aaaaaaaaaaaa"


def test_get_history_marks_head(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    history = svc.get_history()
    assert history[0].is_head is True
    assert history[1].is_head is False


def test_get_history_range(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    history = svc.get_history(range_=":bbbbbbbbbbbb")
    revisions = [h.revision for h in history]
    assert "aaaaaaaaaaaa" in revisions
    assert "bbbbbbbbbbbb" in revisions


# ---------------------------------------------------------------------------
# get_heads
# ---------------------------------------------------------------------------


def test_get_heads_returns_single_head(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    heads = svc.get_heads()
    assert len(heads) == 1
    assert heads[0].revision == "bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# get_branch_points
# ---------------------------------------------------------------------------


def test_get_branch_points_empty_for_linear_chain(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    assert svc.get_branch_points() == []


def test_get_branch_points_detects_fork(tmp_path: Path) -> None:
    rev1, _ = _scaffold_two_revisions(tmp_path)
    versions = tmp_path / "versions"
    rev3 = "cccccccccccc"
    (versions / f"{rev3}_branch.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev3!r}
            down_revision = {rev1!r}
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "branch off first"
            from datetime import datetime
            create_date = datetime(2026, 1, 3)

            def upgrade(op): pass
            def downgrade(op): pass
        """)
    )
    svc = RunicService(tmp_path)
    bps = svc.get_branch_points()
    assert len(bps) == 1
    bp_rev, children = bps[0]
    assert bp_rev.revision == rev1
    assert set(children) == {"bbbbbbbbbbbb", "cccccccccccc"}


# ---------------------------------------------------------------------------
# show_revision
# ---------------------------------------------------------------------------


def test_show_revision_by_full_id(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    rev = svc.show_revision("bbbbbbbbbbbb")
    assert rev.revision == "bbbbbbbbbbbb"
    assert rev.message == "add email index"


def test_show_revision_by_prefix(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    rev = svc.show_revision("bbbb")
    assert rev.revision == "bbbbbbbbbbbb"


def test_show_revision_unknown_raises(tmp_path: Path) -> None:
    _scaffold_two_revisions(tmp_path)
    svc = RunicService(tmp_path)
    from runic.script import RevisionNotFound

    with pytest.raises(RevisionNotFound):
        svc.show_revision("zzzzzzzzzzzz")
