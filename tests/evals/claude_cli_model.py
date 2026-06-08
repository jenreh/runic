"""A key-free DeepEval judge backed by the local ``claude -p`` CLI.

Uses the existing Claude Code authentication on this machine, so the eval suite
runs without an ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``. If you prefer the
standard hosted-API path, swap this for ``deepeval``'s native ``AnthropicModel``
(needs ``ANTHROPIC_API_KEY``) in ``metrics.py``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Pull the first JSON object/array out of a model response."""
    fenced = _JSON_FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    if start == -1:
        return text.strip()
    # Walk to the matching closing bracket for the opening one.
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == opening:
            depth += 1
        elif text[idx] == closing:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return text[start:].strip()


class ClaudeCLIModel(DeepEvalBaseLLM):
    """DeepEval model that shells out to ``claude -p`` for generation."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self._model = model
        super().__init__(model)

    def load_model(self) -> "ClaudeCLIModel":
        return self

    def get_model_name(self) -> str:
        return f"claude-cli:{self._model}"

    def _call(self, prompt: str) -> str:
        claude = shutil.which("claude")
        if claude is None:
            raise RuntimeError("`claude` CLI not found on PATH.")
        proc = subprocess.run(
            [claude, "-p", "--model", self._model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude -p failed (rc={proc.returncode}): {proc.stderr[:500]}"
            )
        return proc.stdout.strip()

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        if schema is None:
            return self._call(prompt)
        instructed = (
            f"{prompt}\n\nRespond with ONLY a JSON object that conforms to this "
            f"JSON schema. No markdown, no prose, no code fences:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        raw = self._call(instructed)
        return schema.model_validate_json(_extract_json(raw))

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        return self.generate(prompt, schema)
