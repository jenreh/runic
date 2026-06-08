# runic-ogm skill — DeepEval suite

LLM-judged evaluation of whether the **runic-ogm skill** (`skill/runic/`) makes
Claude answer real `runic.ogm` questions correctly.

| File | Purpose |
| --- | --- |
| `.dataset.json` | Goldens: `input` (a runic.ogm task) + `expected_output` (reference solution) |
| `runic_orm_app.py` | The app under test — answers a prompt with the skill via `claude -p` |
| `claude_cli_model.py` | Key-free DeepEval judge backed by the local `claude` CLI |
| `metrics.py` | Two `GEval` metrics: `Correctness` and `APIFidelity` |
| `test_runic_orm_skill.py` | Runs the app per golden and asserts the metrics |

## Why it runs in an isolated environment

DeepEval cannot be a normal dependency of this repo: on **Python 3.14** modern
`deepeval` requires `rich<15` while runic depends on `rich>=15`, and the older
`deepeval` that uv backtracks to is broken against the installed `langchain`. So
the suite is committed here but is **not** in `pyproject.toml`; run it from a
throwaway environment instead.

```bash
# one-time: isolated interpreter with deepeval (deepeval brings its own rich)
uv venv /tmp/deepeval-venv --python 3.12
uv pip install --python /tmp/deepeval-venv deepeval

# run the suite (from the repo root)
/tmp/deepeval-venv/bin/deepeval test run tests/evals/test_runic_orm_skill.py
```

## Judging without an API key

Both the app and the judge call the local `claude` CLI (`claude -p`), which uses
your existing Claude Code authentication — **no `ANTHROPIC_API_KEY` needed**.

To use the hosted Anthropic API instead, set `ANTHROPIC_API_KEY` and, in
`metrics.py`, replace `ClaudeCLIModel()` with
`deepeval.models.AnthropicModel("claude-sonnet-4-6")`. Both the judge model and
the app model are then the hosted API.

## Editing the dataset

`.dataset.json` is a plain JSON array of `{ "input", "expected_output" }`
objects. Add or edit goldens freely, then rerun. Keep `expected_output`
describing the *correct runic.ogm approach* so the `Correctness` judge has a
solid reference.
