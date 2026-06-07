import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runic.migrate.exceptions import MultipleHeadsError
from runic.migrate.script import (
    AmbiguousRevision,
    Revision,
    RevisionNotFound,
    ScriptDirectory,
)


@pytest.fixture
def linear_3(tmp_path: Path) -> Path:
    """A → B → C linear chain."""
    versions = tmp_path / "versions"
    versions.mkdir()

    for rev, down, msg, day in [
        ("aaaaaaaaaaaa", None, "first", 1),
        ("bbbbbbbbbbbb", "aaaaaaaaaaaa", "second", 2),
        ("cccccccccccc", "bbbbbbbbbbbb", "third", 3),
    ]:
        (versions / f"{rev}_{msg}.py").write_text(
            textwrap.dedent(f"""\
                revision = {rev!r}
                down_revision = {down!r}
                branch_labels = []
                depends_on = []
                irreversible = False
                snapshot = False
                message = {msg!r}
                from datetime import datetime
                create_date = datetime(2026, 1, {day})

                def upgrade(op):
                    pass

                def downgrade(op):
                    pass
            """)
        )

    return tmp_path


@pytest.fixture
def two_heads(tmp_path: Path) -> Path:
    """A → B and A → C (two heads branching from A)."""
    versions = tmp_path / "versions"
    versions.mkdir()

    for rev, down, msg, day in [
        ("aaaaaaaaaaaa", None, "base", 1),
        ("bbbbbbbbbbbb", "aaaaaaaaaaaa", "branch-b", 2),
        ("cccccccccccc", "aaaaaaaaaaaa", "branch-c", 3),
    ]:
        (versions / f"{rev}_{msg}.py").write_text(
            textwrap.dedent(f"""\
                revision = {rev!r}
                down_revision = {down!r}
                branch_labels = []
                depends_on = []
                irreversible = False
                snapshot = False
                message = {msg!r}
                from datetime import datetime
                create_date = datetime(2026, 1, {day})

                def upgrade(op):
                    pass

                def downgrade(op):
                    pass
            """)
        )

    return tmp_path


# ------------------------------------------------------------------
# get_heads
# ------------------------------------------------------------------


def test_get_heads_single_on_linear(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    heads = sd.get_heads()
    assert len(heads) == 1
    assert heads[0].revision == "cccccccccccc"


def test_get_heads_two_when_branched(two_heads: Path) -> None:
    sd = ScriptDirectory.load(two_heads)
    heads = sd.get_heads()
    assert len(heads) == 2
    rev_ids = {h.revision for h in heads}
    assert rev_ids == {"bbbbbbbbbbbb", "cccccccccccc"}


def test_get_heads_sorted_by_date_desc(two_heads: Path) -> None:
    sd = ScriptDirectory.load(two_heads)
    heads = sd.get_heads()
    assert heads[0].revision == "cccccccccccc"


# ------------------------------------------------------------------
# get_branch_points
# ------------------------------------------------------------------


def test_get_branch_points_none_on_linear(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    assert sd.get_branch_points() == []


def test_get_branch_points_returns_shared_parent(two_heads: Path) -> None:
    sd = ScriptDirectory.load(two_heads)
    bps = sd.get_branch_points()
    assert len(bps) == 1
    assert bps[0].revision == "aaaaaaaaaaaa"


# ------------------------------------------------------------------
# walk_revisions
# ------------------------------------------------------------------


def test_walk_revisions_up_full_chain(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    result = list(sd.walk_revisions(None, None, "up"))
    assert [r.revision for r in result] == [
        "aaaaaaaaaaaa",
        "bbbbbbbbbbbb",
        "cccccccccccc",
    ]


def test_walk_revisions_up_partial(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    result = list(sd.walk_revisions("aaaaaaaaaaaa", "cccccccccccc", "up"))
    assert [r.revision for r in result] == ["bbbbbbbbbbbb", "cccccccccccc"]


def test_walk_revisions_down_full_chain(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    result = list(sd.walk_revisions(None, None, "down"))
    assert [r.revision for r in result] == [
        "cccccccccccc",
        "bbbbbbbbbbbb",
        "aaaaaaaaaaaa",
    ]


def test_walk_revisions_down_partial(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    result = list(sd.walk_revisions("aaaaaaaaaaaa", "cccccccccccc", "down"))
    assert [r.revision for r in result] == ["cccccccccccc", "bbbbbbbbbbbb"]


def test_walk_revisions_up_raises_multiple_heads(two_heads: Path) -> None:
    sd = ScriptDirectory.load(two_heads)
    with pytest.raises(MultipleHeadsError):
        list(sd.walk_revisions(None, None, "up"))


def test_walk_revisions_up_with_explicit_end_no_error(two_heads: Path) -> None:
    sd = ScriptDirectory.load(two_heads)
    result = list(sd.walk_revisions(None, "bbbbbbbbbbbb", "up"))
    assert "bbbbbbbbbbbb" in [r.revision for r in result]


# ------------------------------------------------------------------
# get_revision with special symbols
# ------------------------------------------------------------------


def test_get_revision_head_on_single(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    rev = sd.get_revision("head")
    assert rev.revision == "cccccccccccc"


def test_get_revision_head_raises_multiple(two_heads: Path) -> None:
    sd = ScriptDirectory.load(two_heads)
    with pytest.raises(MultipleHeadsError):
        sd.get_revision("head")


def test_get_revision_base(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    rev = sd.get_revision("base")
    assert rev.revision == "aaaaaaaaaaaa"


def test_get_revision_prefix(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    rev = sd.get_revision("aaaa")
    assert rev.revision == "aaaaaaaaaaaa"


def test_get_revision_ambiguous_prefix(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    # Inject a second revision that shares a prefix with "aaaaaaaaaaaa".
    sd._revisions["aabb11112222"] = Revision(
        revision="aabb11112222",
        down_revision="cccccccccccc",
        branch_labels=[],
        depends_on=[],
        irreversible=False,
        snapshot=False,
        message="extra",
        create_date=datetime(2026, 1, 4, tzinfo=UTC),
        path=linear_3 / "versions" / "extra.py",
    )
    with pytest.raises(AmbiguousRevision):
        sd.get_revision("aa")


def test_get_revision_not_found(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    with pytest.raises(RevisionNotFound):
        sd.get_revision("zzzzzzzzzzzz")


# ------------------------------------------------------------------
# revision_history
# ------------------------------------------------------------------


def test_revision_history_oldest_first(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    hist = sd.revision_history()
    assert [h.revision for h in hist] == [
        "aaaaaaaaaaaa",
        "bbbbbbbbbbbb",
        "cccccccccccc",
    ]


def test_revision_history_head_flag(linear_3: Path) -> None:
    sd = ScriptDirectory.load(linear_3)
    hist = sd.revision_history()
    assert hist[-1].is_head is True
    assert hist[0].is_head is False


def test_revision_history_branch_point_flag(two_heads: Path) -> None:
    sd = ScriptDirectory.load(two_heads)
    hist = sd.revision_history()
    branch_points = [h for h in hist if h.is_branch_point]
    assert len(branch_points) == 1
    assert branch_points[0].revision == "aaaaaaaaaaaa"
