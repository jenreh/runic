"""DeepEval metrics for runic skill evaluations.

Shared judge (key-free ClaudeCLIModel) and two metric sets:

- ``SINGLE_TURN_NO_TRACING_METRICS``  — runic-ogm skill (Node/Edge/Session API)
- ``MIGRATE_METRICS``                 — runic-migrate skill (CLI + op.* API)

To use the standard hosted API instead, set ``ANTHROPIC_API_KEY`` and replace
``_JUDGE`` with ``deepeval.models.AnthropicModel("claude-sonnet-4-6")``.
"""

from __future__ import annotations

from claude_cli_model import ClaudeCLIModel
from deepeval.metrics import BaseMetric, GEval
from deepeval.test_case import LLMTestCaseParams

_JUDGE = ClaudeCLIModel()

_PARAMS = [
    LLMTestCaseParams.INPUT,
    LLMTestCaseParams.ACTUAL_OUTPUT,
    LLMTestCaseParams.EXPECTED_OUTPUT,
]

correctness = GEval(
    name="Correctness",
    criteria=(
        "Judge whether the 'actual output' is a correct, working answer to the "
        "runic.ogm question in 'input', using 'expected output' as the reference "
        "solution. Reward answers that define models with the right Node/Edge "
        "declarations, use the correct Field/Relation options, and run the right "
        "session/query-builder calls. Minor stylistic differences from the "
        "reference are fine; missing or wrong API usage is not."
    ),
    evaluation_params=_PARAMS,
    model=_JUDGE,
    threshold=0.7,
)

api_fidelity = GEval(
    name="APIFidelity",
    evaluation_steps=[
        "Check whether the 'actual output' uses the genuine runic.ogm API as "
        "shown in 'expected output' (Node/Edge with labels=/type=, Field(), "
        "Relation(relationship=, direction=, target=, edge_model=), select()/"
        "session.query(), .where(), session.relate(), get(..., fetch=), etc.).",
        "Penalize SQLAlchemy/Django idioms that do not exist in runic.ogm: "
        ".filter(), .label(), field.desc(), Column, declarative_base, "
        "sessionmaker, objects.filter, query(Model).all().",
        "Penalize invented runic.ogm methods or arguments (e.g. session.run(), "
        "prefetch=, target_model=, .between(), wrong driver import paths).",
        "A high score means the answer would import and run against runic.ogm; a "
        "low score means it would fail because the API does not exist.",
    ],
    evaluation_params=_PARAMS,
    model=_JUDGE,
    threshold=0.7,
)

# Imported by the OGM eval test file.
SINGLE_TURN_NO_TRACING_METRICS: list[BaseMetric] = [correctness, api_fidelity]

# ---------------------------------------------------------------------------
# runic-migrate metrics
# ---------------------------------------------------------------------------

correctness_migrate = GEval(
    name="Correctness",
    criteria=(
        "Judge whether the 'actual output' is a correct, working answer to the "
        "runic.migrate question in 'input', using 'expected output' as the "
        "reference solution. Reward answers that use the right CLI commands and "
        "flags, correct op.* API call signatures, proper migration file fields "
        "(revision, down_revision, irreversible, snapshot, upgrade, downgrade), "
        "and follow the ordering rules (indexes before constraints in upgrade, "
        "constraints before indexes in downgrade). Minor stylistic differences "
        "are fine; wrong commands, invented flags, or missing ordering rules are "
        "not."
    ),
    evaluation_params=_PARAMS,
    model=_JUDGE,
    threshold=0.7,
)

command_fidelity = GEval(
    name="CommandFidelity",
    evaluation_steps=[
        "Check whether the 'actual output' uses the genuine runic CLI commands "
        "and op.* API as shown in 'expected output': runic init/revision/upgrade/"
        "downgrade/current/history/heads/branches/stamp/show/test/merge/check/"
        "validate/run/info/baseline, and op.create_range_index, "
        "op.drop_range_index, op.create_fulltext_index, op.drop_fulltext_index, "
        "op.create_vector_index, op.drop_vector_index, op.create_constraint, "
        "op.drop_constraint, op.rename_property, op.relabel_nodes, op.seed, "
        "op.run_cypher.",
        "Penalize invented CLI flags or subcommands not in the runic CLI: "
        "for example --apply, --dry-run (correct flag is --preview), "
        "--no-downgrade, runic apply, runic status, runic reset.",
        "Penalize invented op.* methods not in the real API: op.add_index(), "
        "op.execute(), op.migrate(), op.alter_property(), op.drop_property().",
        "Penalize Alembic idioms incorrectly transplanted into runic: "
        "op.create_table, op.add_column, op.alter_column, op.execute('ALTER ...').",
        "A high score means the answer would work against the real runic CLI and "
        "op.* API; a low score means it uses commands or methods that do not exist.",
    ],
    evaluation_params=_PARAMS,
    model=_JUDGE,
    threshold=0.7,
)

# Imported by the migrate eval test file.
MIGRATE_METRICS: list[BaseMetric] = [correctness_migrate, command_fidelity]
