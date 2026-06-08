# runic skill — DeepEval suites

LLM-judged evaluations of whether the runic skills make Claude answer real
questions correctly. Two suites share the same isolated environment and judge
model.

---

## runic-ogm skill

| File | Purpose |
| --- | --- |
| `.dataset.json` | Goldens: `input` (runic.ogm task) + `expected_output` (reference solution) |
| `runic_orm_app.py` | App under test — answers a prompt with the skill via `claude -p` |
| `claude_cli_model.py` | Key-free DeepEval judge backed by the local `claude` CLI |
| `metrics.py` | `SINGLE_TURN_NO_TRACING_METRICS`: Correctness + APIFidelity |
| `test_runic_orm_skill.py` | Runs the app per golden and asserts the metrics |

```bash
/tmp/deepeval-venv/bin/deepeval test run tests/evals/test_runic_orm_skill.py
```

---

## runic-migrate skill

| File | Purpose |
| --- | --- |
| `.migrate_dataset.json` | Goldens: `input` (runic.migrate task) + `expected_output` (reference solution) |
| `runic_migrate_app.py` | App under test — answers with SKILL.md + op-api.md + advanced.md via `claude -p` |
| `metrics.py` | `MIGRATE_METRICS`: Correctness + CommandFidelity |
| `test_runic_migrate_skill.py` | Runs the app per golden and asserts the metrics |

```bash
/tmp/deepeval-venv/bin/deepeval test run tests/evals/test_runic_migrate_skill.py
```

Run both suites in parallel with `--num-processes 5` to manage wall-clock time
(each golden calls `claude -p` twice: once for the app answer, once per judge
metric).

---

## Why it runs in an isolated environment

DeepEval cannot be a normal dependency of this repo: on **Python 3.14** modern
`deepeval` requires `rich<15` while runic depends on `rich>=15`, and the older
`deepeval` that uv backtracks to is broken against the installed `langchain`. So
the suites are committed here but are **not** in `pyproject.toml`; run them from
a throwaway environment instead.

```bash
# one-time: isolated interpreter with deepeval (deepeval brings its own rich)
uv venv /tmp/deepeval-venv --python 3.12
uv pip install --python /tmp/deepeval-venv deepeval

# run either suite (from the repo root)
/tmp/deepeval-venv/bin/deepeval test run tests/evals/test_runic_orm_skill.py
/tmp/deepeval-venv/bin/deepeval test run tests/evals/test_runic_migrate_skill.py
```

---

## Judging without an API key

Both the app and the judge call the local `claude` CLI (`claude -p`), which uses
your existing Claude Code authentication — **no `ANTHROPIC_API_KEY` needed**.

To use the hosted Anthropic API instead, set `ANTHROPIC_API_KEY` and, in
`metrics.py`, replace `ClaudeCLIModel()` with
`deepeval.models.AnthropicModel("claude-sonnet-4-6")`.

---

## Editing the datasets

`.dataset.json` and `.migrate_dataset.json` are plain JSON arrays of
`{ "input", "expected_output" }` objects. Add or edit goldens freely, then
rerun. Keep `expected_output` describing the *correct runic approach* so the
Correctness judge has a solid reference.

**Note on dataset generation:** these goldens were hand-curated against the
actual implementation rather than generated with `deepeval generate`. This is a
deliberate deviation from the deepeval skill's default — the skill's API surface
is too narrow for docs-based generation to produce grounded `expected_output`
values, and circular generation (LLM derives goldens from the same skill it
evaluates) would undermine the eval's signal. Augment by adding edge cases that
have tripped users up.
