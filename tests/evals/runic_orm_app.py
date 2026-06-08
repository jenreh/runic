"""The 'app under test': Claude answering runic.ogm questions WITH the skill.

``run_ai_app(prompt)`` invokes ``claude -p`` with the runic-ogm SKILL.md prepended
as the source of truth, so the eval measures *skill-guided* answers. It uses the
local Claude Code authentication (no API key required).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# tests/evals/runic_orm_app.py -> repo root is parents[2]
_SKILL_PATH = Path(__file__).resolve().parents[2] / "skill" / "runic" / "SKILL.md"

_SYSTEM = (
    "You are answering a developer's question about the `runic.ogm` Python "
    "library (a SQLModel-style OGM for Cypher graph databases). Use the skill "
    "documentation below as the authoritative source for the runic.ogm API. "
    "Answer with correct, idiomatic runic.ogm code and a brief explanation; do "
    "not invent API that is not in the skill.\n\n<skill>\n{skill}\n</skill>\n\n"
    "Question:\n{question}\n"
)


def run_ai_app(prompt: str, model: str = "claude-sonnet-4-6") -> str:
    """Return Claude's skill-guided answer to *prompt*."""
    claude = shutil.which("claude")
    if claude is None:
        raise RuntimeError("`claude` CLI not found on PATH.")
    skill_text = _SKILL_PATH.read_text(encoding="utf-8")
    full_prompt = _SYSTEM.format(skill=skill_text, question=prompt)
    proc = subprocess.run(  # noqa: S603
        [claude, "-p", "--model", model],
        input=full_prompt,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p failed (rc={proc.returncode}): {proc.stderr[:500]}"
        )
    return proc.stdout.strip()
