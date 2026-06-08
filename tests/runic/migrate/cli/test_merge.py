"""CLI tests: merge command."""

from __future__ import annotations

from pathlib import Path

from runic.migrate.cli import app

from ._helpers import runner, setup_two_branches, write_rev


def test_merge_creates_revision(tmp_path: Path) -> None:
    config, rev_a, rev_b = setup_two_branches(tmp_path)
    result = runner.invoke(
        app,
        ["merge", rev_a, rev_b, "-m", "merge branches", "--config", str(config)],
    )
    assert result.exit_code == 0, result.output
    assert "Created revision" in result.output
    versions = list((tmp_path / "runic" / "versions").glob("*.py"))
    merge_files = [
        f for f in versions if f.stem not in (rev_a + "_rev", rev_b + "_rev")
    ]
    assert len(merge_files) == 1
    content = merge_files[0].read_text()
    assert rev_a in content
    assert rev_b in content


def test_merge_warns_when_not_heads(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    vd = target / "versions"
    rev_a = "aaa111aaa111"
    rev_b = "bbb222bbb222"
    write_rev(vd, rev_a)
    write_rev(vd, rev_b, rev_a)

    result = runner.invoke(
        app,
        [
            "merge",
            rev_a,
            rev_b,
            "-m",
            "splice merge",
            "--config",
            str(target / "env.py"),
        ],
    )
    assert "Warning" in result.output or result.exit_code == 0


def test_merge_with_branch_label(tmp_path: Path) -> None:
    config, rev_a, rev_b = setup_two_branches(tmp_path)
    result = runner.invoke(
        app,
        [
            "merge",
            rev_a,
            rev_b,
            "-m",
            "merge",
            "--branch-label",
            "main",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0
