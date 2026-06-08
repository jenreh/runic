from scripts.generate_changelog import (
    _assemble,
    _normalize_repo_url,
    _render_commit_line,
    commit_link,
    extract_issue_refs,
    is_breaking,
    normalize_type,
    parse_subject,
)

REPO = "https://github.com/org/repo"


# ---------------------------------------------------------------------------
# parse_subject
# ---------------------------------------------------------------------------


def test_parse_subject_feat_no_scope() -> None:
    assert parse_subject("feat: add new API") == ("feat", "", "add new API")


def test_parse_subject_fix_with_scope() -> None:
    assert parse_subject("fix(parser): handle null input") == (
        "fix",
        "parser",
        "handle null input",
    )


def test_parse_subject_breaking_bang() -> None:
    type_, scope, desc = parse_subject("feat!: drop old interface")
    assert type_ == "feat"
    assert scope == ""
    assert desc == "drop old interface"


def test_parse_subject_breaking_scoped_bang() -> None:
    type_, scope, desc = parse_subject("fix(core)!: drop Python 3.10 support")
    assert type_ == "fix"
    assert scope == "core"
    assert desc == "drop Python 3.10 support"


def test_parse_subject_uppercase_type() -> None:
    type_, _, _ = parse_subject("Feat: something")
    assert type_ == "feat"


def test_parse_subject_non_conventional() -> None:
    assert parse_subject("Updated README") == ("other", "", "Updated README")


# ---------------------------------------------------------------------------
# normalize_type
# ---------------------------------------------------------------------------


def test_normalize_type_feature_alias() -> None:
    assert normalize_type("feature") == "feat"


def test_normalize_type_passthrough() -> None:
    assert normalize_type("fix") == "fix"
    assert normalize_type("chore") == "chore"
    assert normalize_type("other") == "other"


# ---------------------------------------------------------------------------
# is_breaking
# ---------------------------------------------------------------------------


def test_is_breaking_bang_subject() -> None:
    assert is_breaking("feat!: remove deprecated field", "") is True


def test_is_breaking_scoped_bang() -> None:
    assert is_breaking("fix(api)!: drop Python 3.10", "") is True


def test_is_breaking_body_marker() -> None:
    assert (
        is_breaking("feat: add new option", "BREAKING CHANGE: old flag removed") is True
    )


def test_is_breaking_false_normal() -> None:
    assert is_breaking("feat: add feature", "") is False


def test_is_breaking_false_bang_in_desc() -> None:
    assert is_breaking("feat: great thing!", "") is False


# ---------------------------------------------------------------------------
# extract_issue_refs
# ---------------------------------------------------------------------------


def test_extract_issue_refs_closes_in_subject() -> None:
    assert extract_issue_refs("fix: close bug closes #42", "") == [42]


def test_extract_issue_refs_inline_pr_ref() -> None:
    assert extract_issue_refs("feat: new thing (#99)", "") == [99]


def test_extract_issue_refs_multiple_body() -> None:
    refs = extract_issue_refs("fix: something", "fixes #10\ncloses #11")
    assert refs == [10, 11]


def test_extract_issue_refs_deduplication() -> None:
    refs = extract_issue_refs("closes #5", "closes #5")
    assert refs == [5]


def test_extract_issue_refs_case_insensitive() -> None:
    assert extract_issue_refs("Closes #1", "FIXES #2") == [1, 2]


def test_extract_issue_refs_none() -> None:
    assert extract_issue_refs("chore: update deps", "") == []


# ---------------------------------------------------------------------------
# commit_link
# ---------------------------------------------------------------------------


def test_commit_link_truncates_to_7() -> None:
    result = commit_link(REPO, "abc123def456")
    assert result == f"[`abc123d`]({REPO}/commit/abc123def456)"


# ---------------------------------------------------------------------------
# _normalize_repo_url
# ---------------------------------------------------------------------------


def test_normalize_repo_url_ssh() -> None:
    assert (
        _normalize_repo_url("git@github.com:owner/repo")
        == "https://github.com/owner/repo"
    )


def test_normalize_repo_url_https_passthrough() -> None:
    assert (
        _normalize_repo_url("https://github.com/owner/repo")
        == "https://github.com/owner/repo"
    )


def test_normalize_repo_url_ssh_other_host() -> None:
    assert (
        _normalize_repo_url("git@gitlab.com:org/proj") == "https://gitlab.com/org/proj"
    )


# ---------------------------------------------------------------------------
# _render_commit_line
# ---------------------------------------------------------------------------


def test_render_commit_line_scoped() -> None:
    line = _render_commit_line("parser", "handle null input", "abc123def456", [], REPO)
    assert line.startswith("- **parser**:")
    assert "Handle null input" in line
    assert "abc123d" in line


def test_render_commit_line_unscoped() -> None:
    line = _render_commit_line("", "add feature", "abc123def456", [], REPO)
    assert line.startswith("- Add feature")


def test_render_commit_line_strips_inline_pr_ref() -> None:
    line = _render_commit_line("", "add thing (#42)", "abc123def456", [42], REPO)
    assert "(#42)" not in line
    assert "#42" in line


def test_render_commit_line_capitalizes_desc() -> None:
    line = _render_commit_line("", "lowercase desc", "abc123def456", [], REPO)
    assert "Lowercase desc" in line


# ---------------------------------------------------------------------------
# _assemble
# ---------------------------------------------------------------------------


def _commit(
    subject: str, body: str = "", hash_: str = "abc123def456"
) -> dict[str, str]:
    return {"hash": hash_, "subject": subject, "body": body}


def test_assemble_empty_commits() -> None:
    result = _assemble([], "", [], "v1.0.0", "v0.9.0", REPO)
    assert result == "## v1.0.0\n\nNo changes recorded."


def test_assemble_basic_structure() -> None:
    commits = [_commit("feat: add login")]
    result = _assemble(commits, "", [], "v1.0.0", "v0.9.0", REPO)
    assert "## What's Changed" in result
    assert "### Features" in result
    assert "Add login" in result


def test_assemble_with_summary() -> None:
    commits = [_commit("fix: patch bug")]
    result = _assemble(commits, "Great release!", [], "v1.0.0", "v0.9.0", REPO)
    assert result.startswith("Great release!")


def test_assemble_breaking_changes_section() -> None:
    commits = [
        _commit("feat!: drop old API"),
        _commit("fix: patch bug"),
    ]
    result = _assemble(commits, "", [], "v1.0.0", "v0.9.0", REPO)
    assert "## Breaking Changes" in result
    breaking_pos = result.index("## Breaking Changes")
    whats_changed_pos = result.index("## What's Changed")
    assert breaking_pos < whats_changed_pos


def test_assemble_single_contributor() -> None:
    commits = [_commit("feat: add thing")]
    result = _assemble(commits, "", ["Alice"], "v1.0.0", "v0.9.0", REPO)
    assert "Thanks to Alice" in result


def test_assemble_multiple_contributors() -> None:
    commits = [_commit("feat: add thing")]
    result = _assemble(commits, "", ["Alice", "Bob", "Carol"], "v1.0.0", "v0.9.0", REPO)
    assert "Alice, Bob and Carol" in result


def test_assemble_no_previous_tag_omits_compare_link() -> None:
    commits = [_commit("feat: first release")]
    result = _assemble(commits, "", [], "v1.0.0", "", REPO)
    assert "Full Changelog" not in result


def test_assemble_with_previous_tag_includes_compare_link() -> None:
    commits = [_commit("feat: add thing")]
    result = _assemble(commits, "", [], "v1.0.0", "v0.9.0", REPO)
    assert f"**Full Changelog**: {REPO}/compare/v0.9.0...v1.0.0" in result


def test_assemble_type_ordering() -> None:
    commits = [
        _commit("chore: bump deps", hash_="aaa0000000"),
        _commit("fix: patch bug", hash_="bbb0000000"),
        _commit("feat: new thing", hash_="ccc0000000"),
    ]
    result = _assemble(commits, "", [], "v1.0.0", "v0.9.0", REPO)
    feat_pos = result.index("### Features")
    fix_pos = result.index("### Bug Fixes")
    chore_pos = result.index("### Chores")
    assert feat_pos < fix_pos < chore_pos


def test_assemble_feature_alias_normalized() -> None:
    commits = [_commit("feature: add thing")]
    result = _assemble(commits, "", [], "v1.0.0", "v0.9.0", REPO)
    assert "### Features" in result
    assert "### feature" not in result.lower() or "Features" in result
