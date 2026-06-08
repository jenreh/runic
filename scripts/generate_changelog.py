"""Generate a user-friendly changelog from git commits between the previous tag and HEAD.

Usage:
    uv run python scripts/generate_changelog.py v1.2.3 [OPTIONS]

Shell completions (zsh):
    uv run python scripts/generate_changelog.py --completion zsh >> ~/.zshrc
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from typer.completion import get_completion_script  # noqa: E402

_STDERR = Console(stderr=True)

COMMIT_TYPES: dict[str, str] = {
    "feat": "Features",
    "feature": "Features",
    "fix": "Bug Fixes",
    "perf": "Performance",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "test": "Tests",
    "chore": "Chores",
    "build": "Build",
    "ci": "CI",
    "style": "Style",
}

TYPE_ORDER = [
    "feat",
    "fix",
    "perf",
    "refactor",
    "docs",
    "test",
    "chore",
    "build",
    "ci",
    "style",
    "other",
]

_SKIP_PATTERNS = re.compile(r"^chore:\s+release\s+v\d", re.IGNORECASE)

# Matches "Closes/Fixes/Resolves #N" or "(#N)"
_ISSUE_REF_RE = re.compile(
    r"(?:closes?|fixes?|resolves?)\s+#(\d+)|\(#(\d+)\)",
    re.IGNORECASE,
)

# Matches conventional commit breaking-change marker in subject
_BREAKING_SUBJECT_RE = re.compile(r"^\w+(?:\([^)]+\))?!:")

_SUMMARY_PROMPT = (
    "Write the opening paragraph for the GitHub release notes of **runic {version}** "
    "(a Python graph schema migration and OGM library for Cypher-based graph "
    "databases like FalkorDB).\n\n"
    "Commits since {previous_tag}:\n{commits}\n\n"
    "Instructions:\n"
    "- Start with a single punchy sentence naming the 1-2 most impactful user-facing changes by name.\n"
    "- Follow with 1-2 sentences covering the other notable themes (fixes, improvements, etc.).\n"
    "- If any commit subject ends with '!' after the type (e.g. feat!:) or the body contains "
    "'BREAKING CHANGE:', explicitly flag that in the summary.\n"
    "- Skip pure internal work (refactors, chores) unless they affect the public API.\n"
    "- Maximum 3 sentences total. Be concrete — name features, not vague themes.\n"
    "- Output only the paragraph text, no markdown headers."
)

# SSH remote pattern: git@HOST:OWNER/REPO
_SSH_REMOTE_RE = re.compile(r"^git@([^:]+):(.+)$")


class Backend(StrEnum):
    auto = "auto"
    claude = "claude"
    github = "github"


app = typer.Typer(
    help="Generate user-friendly GitHub release notes from git commits.",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, required: bool = False) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603, PLW1510
    if result.returncode != 0:
        _STDERR.print(
            f"[yellow]warning:[/yellow] command failed (exit {result.returncode}): {' '.join(cmd)}\n{result.stderr.strip()}",
        )
        if required:
            raise typer.Exit(1)
        return ""
    return result.stdout.strip()


def _normalize_repo_url(raw: str) -> str:
    """Convert SSH remote URLs to HTTPS so commit/issue links are valid."""
    m = _SSH_REMOTE_RE.match(raw)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return raw


def get_previous_tag(new_tag: str) -> str:
    result = subprocess.run(  # noqa: S603, PLW1510
        ["git", "describe", "--tags", "--abbrev=0", f"{new_tag}^"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _STDERR.print(
            f"[yellow]warning:[/yellow] could not resolve previous tag from {new_tag!r}; trying HEAD^",
        )
        result = subprocess.run(  # noqa: S603, PLW1510
            ["git", "describe", "--tags", "--abbrev=0", "HEAD^"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode == 0:
        return result.stdout.strip()
    _STDERR.print(
        "[yellow]warning:[/yellow] no previous tag found; "
        "changelog will include all commits. "
        "Pass a previous tag explicitly if this is a first release."
    )
    return ""


def get_commits(since_tag: str) -> list[dict[str, str]]:
    """Return commits with hash, subject, and body since since_tag."""
    range_spec = f"{since_tag}..HEAD" if since_tag else "HEAD"
    # \x1e (ASCII record separator) delimits commits; \x00 delimits fields within a commit
    raw = _run(["git", "log", range_spec, "--pretty=format:%H%x00%s%x00%b%x1e"])
    commits = []
    for entry in raw.split("\x1e"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("\x00", 2)
        if len(parts) >= 2 and parts[0].strip():
            subject = parts[1].strip()
            if not _SKIP_PATTERNS.match(subject):
                commits.append(
                    {
                        "hash": parts[0].strip(),
                        "subject": subject,
                        "body": parts[2].strip() if len(parts) > 2 else "",
                    }
                )
    return commits


def get_contributors(since_tag: str) -> list[str]:
    """Return sorted unique author names excluding the current git user."""
    range_spec = f"{since_tag}..HEAD" if since_tag else "HEAD"
    raw = _run(["git", "log", range_spec, "--format=%aN"])
    owner = _run(["git", "config", "user.name"])
    if not owner:
        _STDERR.print(
            "[yellow]warning:[/yellow] git user.name is not set; "
            "contributor list may include the repo owner"
        )
    names = {n.strip() for n in raw.splitlines() if n.strip()}
    return sorted(names - {owner})


def parse_subject(subject: str) -> tuple[str, str, str]:
    """Return (type, scope, description) from a conventional commit subject."""
    match = re.match(r"^(\w+)(?:\(([^)]+)\))?!?:\s*(.+)$", subject)
    if match:
        return match.group(1).lower(), match.group(2) or "", match.group(3)
    return "other", "", subject


def normalize_type(type_: str) -> str:
    return "feat" if type_ == "feature" else type_


def is_breaking(subject: str, body: str) -> bool:
    return bool(_BREAKING_SUBJECT_RE.match(subject)) or "BREAKING CHANGE:" in body


def extract_issue_refs(subject: str, body: str) -> list[int]:
    """Return sorted unique issue/PR numbers referenced in subject or body."""
    refs: set[int] = set()
    for m in _ISSUE_REF_RE.finditer(f"{subject}\n{body}"):
        num = m.group(1) or m.group(2)
        refs.add(int(num))
    return sorted(refs)


def commit_link(repo_url: str, hash_: str) -> str:
    return f"[`{hash_[:7]}`]({repo_url}/commit/{hash_})"


def _ref_links(refs: list[int], repo_url: str) -> str:
    if not refs:
        return ""
    return " " + " ".join(f"([#{n}]({repo_url}/issues/{n}))" for n in refs)


# ---------------------------------------------------------------------------
# AI summary backends
# ---------------------------------------------------------------------------


def _via_claude(prompt: str) -> str:
    bin_ = shutil.which("claude")
    if not bin_:
        return ""
    try:
        result = subprocess.run(  # noqa: S603
            [bin_, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            _STDERR.print(
                f"[yellow]warning:[/yellow] claude CLI exited {result.returncode}: {result.stderr.strip() or '(no stderr)'}",
            )
            return ""
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        _STDERR.print(
            "[yellow]warning:[/yellow] claude CLI timed out after 60 s; skipping"
        )
        return ""
    except OSError as exc:
        _STDERR.print(f"[yellow]warning:[/yellow] could not launch claude CLI: {exc}")
        return ""


def _via_github_models(prompt: str) -> str:
    """Call the GitHub Models inference API using the stored gh auth token."""
    gh_bin = shutil.which("gh")
    if not gh_bin:
        return ""
    token_result = subprocess.run(  # noqa: S603
        [gh_bin, "auth", "token"],
        capture_output=True,
        text=True,
        check=False,
    )
    if token_result.returncode != 0:
        _STDERR.print(
            f"[yellow]warning:[/yellow] `gh auth token` failed; skipping GitHub Models: {token_result.stderr.strip()}",
        )
        return ""
    token = token_result.stdout.strip()
    payload = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300,
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310
        "https://models.inference.ai.azure.com/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        _STDERR.print(
            f"[yellow]warning:[/yellow] GitHub Models API returned HTTP {exc.code} {exc.reason}; skipping AI summary",
        )
        return ""
    except urllib.error.URLError as exc:
        _STDERR.print(
            f"[yellow]warning:[/yellow] GitHub Models API unreachable: {exc.reason}; skipping AI summary",
        )
        return ""
    except (KeyError, IndexError, AttributeError, json.JSONDecodeError) as exc:
        _STDERR.print(
            f"[yellow]warning:[/yellow] unexpected GitHub Models response: {exc}; skipping AI summary",
        )
        return ""


_BACKEND_FNS: dict[Backend, list[Callable[[str], str]]] = {
    Backend.auto: [_via_claude, _via_github_models],
    Backend.claude: [_via_claude],
    Backend.github: [_via_github_models],
}


def ai_summary(
    commits: list[dict[str, str]],
    version: str,
    previous_tag: str,
    backend: Backend,
) -> str:
    commit_list = "\n".join(f"- {c['subject']}" for c in commits)
    prompt = _SUMMARY_PROMPT.format(
        version=version, previous_tag=previous_tag, commits=commit_list
    )
    for fn in _BACKEND_FNS[backend]:
        result = fn(prompt)
        if result:
            return result
    if _BACKEND_FNS[backend]:
        _STDERR.print(
            "[yellow]warning:[/yellow] all AI backends failed; "
            "release notes will not include an AI summary"
        )
    return ""


# ---------------------------------------------------------------------------
# Changelog assembly
# ---------------------------------------------------------------------------


_INLINE_PARENS_RE = re.compile(r"\s*\(#\d+\)")


def _render_commit_line(
    scope: str,
    desc: str,
    hash_: str,
    refs: list[int],
    repo_url: str,
) -> str:
    link = commit_link(repo_url, hash_)
    ref_str = _ref_links(refs, repo_url)
    # Strip bare (#N) from description — they're rendered as links via ref_str
    stripped = _INLINE_PARENS_RE.sub("", desc).strip()
    desc_clean = stripped[0].upper() + stripped[1:] if stripped else stripped
    body = f"{desc_clean} {link}{ref_str}"
    return f"- **{scope}**: {body}" if scope else f"- {body}"


def _assemble(
    commits: list[dict[str, str]],
    summary: str,
    contributors: list[str],
    version: str,
    previous_tag: str,
    repo_url: str,
) -> str:
    """Build the markdown string from pre-fetched data. Pure — no I/O."""
    if not commits:
        return f"## {version}\n\nNo changes recorded."

    breaking = [c for c in commits if is_breaking(c["subject"], c["body"])]
    regular = [c for c in commits if not is_breaking(c["subject"], c["body"])]

    grouped: dict[str, list[tuple[str, str, str, list[int]]]] = defaultdict(list)
    for commit in regular:
        type_, scope, desc = parse_subject(commit["subject"])
        refs = extract_issue_refs(commit["subject"], commit["body"])
        grouped[normalize_type(type_)].append((scope, desc, commit["hash"], refs))

    lines: list[str] = []

    if summary:
        lines += [summary, ""]

    if breaking:
        lines += ["## Breaking Changes", ""]
        for commit in breaking:
            _, scope, desc = parse_subject(commit["subject"])
            refs = extract_issue_refs(commit["subject"], commit["body"])
            lines.append(
                _render_commit_line(scope, desc, commit["hash"], refs, repo_url)
            )
        lines.append("")

    lines += ["## What's Changed", ""]

    for key in TYPE_ORDER:
        items = grouped.get(key, [])
        if not items:
            continue
        title = COMMIT_TYPES.get(key, key.capitalize())
        lines += [f"### {title}", ""]
        for scope, desc, hash_, refs in items:
            lines.append(_render_commit_line(scope, desc, hash_, refs, repo_url))
        lines.append("")

    if contributors:
        lines += ["## Contributors", ""]
        if len(contributors) == 1:
            thanks = contributors[0]
        else:
            thanks = ", ".join(contributors[:-1]) + f" and {contributors[-1]}"
        lines += [f"Thanks to {thanks} for contributions to this release.", ""]

    if previous_tag:
        lines.append(
            f"**Full Changelog**: {repo_url}/compare/{previous_tag}...{version}"
        )

    return "\n".join(lines)


def generate(
    version: str,
    previous_tag: str,
    repo_url: str,
    *,
    skip_ai: bool,
    backend: Backend,
) -> str:
    """Programmatic entry point (no progress display)."""
    commits = get_commits(previous_tag)
    summary = ai_summary(commits, version, previous_tag, backend) if not skip_ai else ""
    contributors = get_contributors(previous_tag)
    return _assemble(commits, summary, contributors, version, previous_tag, repo_url)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=_STDERR,
        transient=True,
    )


def _completion_callback(
    ctx: typer.Context,
    _param: typer.CallbackParam,
    value: str | None,
) -> str | None:
    if not value or ctx.resilient_parsing:
        return value
    typer.echo(
        get_completion_script(
            prog_name="generate_changelog",
            complete_var="_GENERATE_CHANGELOG_COMPLETE",
            shell=value,
        )
    )
    raise typer.Exit()


@app.command()
def main(
    version: Annotated[
        str,
        typer.Argument(help="New version tag, e.g. [cyan]v1.2.3[/cyan]"),
    ],
    no_ai: Annotated[
        bool,
        typer.Option("--no-ai", help="Skip the AI-generated narrative summary."),
    ] = False,
    backend: Annotated[
        Backend,
        typer.Option(
            help="AI backend to use for the summary. "
            "[dim]auto[/dim] tries Claude first, then GitHub Models.",
        ),
    ] = Backend.auto,
    completion: Annotated[
        str | None,
        typer.Option(
            "--completion",
            metavar="SHELL",
            help="Print the completion script for [cyan]SHELL[/cyan] (bash, zsh, fish) and exit. "
            "Use this when auto-detection via [dim]--show-completion[/dim] fails "
            "(e.g. inside [dim]uv run[/dim]).",
            is_eager=True,
            callback=_completion_callback,
        ),
    ] = None,
) -> None:
    """Generate user-friendly GitHub release notes from git commits.

    Collects commits between the previous git tag and HEAD, groups them by
    conventional-commit type, and prepends an AI-written narrative summary.
    Issue/PR references, breaking changes, and contributor credits are
    automatically extracted from commit messages.

    \b
    Install zsh completions (auto-detect shell):
        uv run python scripts/generate_changelog.py --install-completion

    Install zsh completions (explicit, works inside uv run):
        uv run python scripts/generate_changelog.py --completion zsh >> ~/.zshrc
    """
    previous_tag = get_previous_tag(version)
    raw_remote = _run(["git", "remote", "get-url", "origin"], required=True)
    repo_url = _normalize_repo_url(raw_remote.removesuffix(".git"))

    total_steps = 2 if no_ai else 3

    with _make_progress() as progress:
        task = progress.add_task("Collecting commits...", total=total_steps)

        commits = get_commits(previous_tag)
        contributors = get_contributors(previous_tag)
        progress.advance(task)

        summary = ""
        if not no_ai:
            progress.update(task, description="Generating AI summary...")
            summary = ai_summary(commits, version, previous_tag, backend)
            progress.advance(task)

        progress.update(task, description="Assembling release notes...")
        result = _assemble(
            commits, summary, contributors, version, previous_tag, repo_url
        )
        progress.advance(task)

    typer.echo(result)


if __name__ == "__main__":
    app()
