from __future__ import annotations

import contextlib
import logging
import secrets
from pathlib import Path
from typing import Annotated, Any

import typer

log = logging.getLogger(__name__)

app = typer.Typer(name="runic", help="FalkorDB migration tool", no_args_is_help=True)

_DEFAULT_CONFIG = Path("runic/env.py")


def _exec_env(config: Path, preview: bool = False) -> None:  # noqa: ARG001
    if not config.exists():
        typer.echo(
            f"Error: config not found at {config}. Run `runic init` first.",
            err=True,
        )
        raise typer.Exit(code=1)
    namespace: dict = {"__file__": str(config), "__name__": "__main__"}
    exec(config.read_text(), namespace)  # noqa: S102


def _get_script_location(config: Path) -> Path:
    return config.parent


# ---------------------------------------------------------------------------
# Phase 0 commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    directory: Annotated[
        Path, typer.Argument(help="Migration directory to scaffold")
    ] = Path("runic"),
    force: Annotated[bool, typer.Option("--force", help="Overwrite if exists")] = False,
) -> None:
    """Scaffold a new runic migration environment."""
    from runic.service import RunicService

    try:
        RunicService.init(directory, force=force)
    except FileExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Created runic environment at {directory}/")
    typer.echo(f"  {directory}/env.py")
    typer.echo(f"  {directory}/script.py.mako")
    typer.echo(f"  {directory}/versions/")


@app.command()
def revision(
    message: Annotated[
        str, typer.Option("-m", "--message", help="Short description of this revision")
    ],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    head: Annotated[str | None, typer.Option("--head")] = None,
    rev_id: Annotated[str | None, typer.Option("--rev-id")] = None,
) -> None:
    """Create a new migration revision script."""
    from runic.service import RunicService

    script_location = _get_script_location(config)
    svc = RunicService(script_location)
    path = svc.create_revision(message, head, rev_id)
    typer.echo(f"Created revision: {path}")


@app.command()
def upgrade(
    target: Annotated[str, typer.Argument()] = "head",
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    preview: Annotated[bool, typer.Option("--preview")] = False,
) -> None:
    """Apply migrations up to target (default: head)."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    if preview:
        ctx.enable_preview()

    ctx.upgrade(target)

    if preview and ctx.preview_log:
        for line in ctx.preview_log:
            typer.echo(line)
    elif preview:
        typer.echo("(no operations — nothing to upgrade)")
    else:
        typer.echo(f"Upgraded to: {target}")


@app.command()
def downgrade(
    target: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    force: Annotated[bool, typer.Option("--force")] = False,
    preview: Annotated[bool, typer.Option("--preview")] = False,
) -> None:
    """Revert migrations to target revision (or 'base')."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    if preview:
        ctx.enable_preview()

    ctx.downgrade(target, force=force)

    if preview and ctx.preview_log:
        for line in ctx.preview_log:
            typer.echo(line)
    elif preview:
        typer.echo("(no operations — nothing to downgrade)")
    else:
        typer.echo(f"Downgraded to: {target}")


@app.command()
def current(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Show the currently applied revision."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    rev_id = ctx.current()
    if rev_id is None:
        typer.echo("<none>")
        return

    message = ctx.get_revision_message(rev_id)
    if message:
        typer.echo(f"{rev_id} — {message}")
    else:
        typer.echo(rev_id)


# ---------------------------------------------------------------------------
# Phase 1 commands
# ---------------------------------------------------------------------------


@app.command()
def history(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
    indicate_current: Annotated[bool, typer.Option("--indicate-current")] = False,
    range_: Annotated[
        str | None, typer.Option("--range", help="Inclusive range start:end")
    ] = None,
) -> None:
    """Print all revisions chronologically (newest first)."""
    from runic.service import RunicService

    script_location = _get_script_location(config)
    svc = RunicService(script_location)

    current_rev: str | None = None
    if indicate_current:
        _exec_env(config)
        from runic.context import get

        current_rev = get().current()

    history_items = svc.get_history(range_)

    for info in history_items:
        tags = []
        if info.is_head:
            tags.append("head")
        if indicate_current and current_rev == info.revision:
            tags.append("current")

        tag_str = f"({', '.join(tags)})" if tags else ""
        line = f"{info.revision:<13}  {tag_str:<20}  {info.message}"
        if verbose:
            line += f"\n    create_date:   {info.create_date}"
            line += f"\n    down_revision: {info.down_revision}"
            if info.is_branch_point:
                line += "\n    [branch point]"
        typer.echo(line)


@app.command()
def heads(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Print all head revisions."""
    from runic.service import RunicService

    script_location = _get_script_location(config)
    svc = RunicService(script_location)
    heads_list = svc.get_heads()

    suffix = (
        "(single head)"
        if len(heads_list) == 1
        else "(MULTIPLE HEADS — use merge to resolve)"
    )
    for head in heads_list:
        typer.echo(f"{head.revision}  {head.message}  {suffix}")


@app.command()
def branches(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Print all branch-point revisions."""
    from runic.service import RunicService

    script_location = _get_script_location(config)
    svc = RunicService(script_location)

    for bp, children in svc.get_branch_points():
        typer.echo(f"{bp.revision}  {bp.message}  {children}")


@app.command()
def stamp(
    target: Annotated[str, typer.Argument(help="Revision id, 'base', or 'heads'")],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    purge: Annotated[
        bool, typer.Option("--purge", help="Clear version node before stamping")
    ] = False,
) -> None:
    """Set the version pointer without running migrations."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    ctx.stamp(target, purge=purge)

    if target == "base":
        typer.echo("Stamped: <none>")
    else:
        typer.echo(f"Stamped: {target}")


@app.command()
def show(
    rev: Annotated[str, typer.Argument(help="Revision id or unique prefix")],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Print full metadata for a single revision."""
    from runic.script import RevisionNotFound
    from runic.service import RunicService

    script_location = _get_script_location(config)
    svc = RunicService(script_location)

    try:
        revision = svc.show_revision(rev)
    except RevisionNotFound as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Revision ID:   {revision.revision}")
    typer.echo(f"Revises:       {revision.down_revision or '<base>'}")
    typer.echo(f"Message:       {revision.message}")
    typer.echo(f"Create Date:   {revision.create_date}")
    typer.echo(f"Irreversible:  {revision.irreversible}")
    typer.echo(f"Snapshot:      {revision.snapshot}")
    typer.echo(f"Branch Labels: {revision.branch_labels}")
    typer.echo(f"Depends On:    {revision.depends_on}")
    typer.echo(f"Path:          {revision.path}")


# ---------------------------------------------------------------------------
# Phase 3 — test command helpers
# ---------------------------------------------------------------------------


def _entity_count(graph: Any) -> int:
    result = graph.query(
        "MATCH (n) WHERE NOT n:_FalkorMigrateVersion RETURN count(n) AS c"
    )
    return int(result.result_set[0][0]) if result.result_set else 0


def _index_count(graph: Any) -> int:
    result = graph.query("CALL db.indexes() YIELD label RETURN count(label) AS c")
    return int(result.result_set[0][0]) if result.result_set else 0


def _constraint_count(graph: Any) -> int:
    result = graph.query("CALL db.constraints() YIELD type RETURN count(type) AS c")
    return int(result.result_set[0][0]) if result.result_set else 0


# ---------------------------------------------------------------------------
# Phase 3 — test command
# ---------------------------------------------------------------------------


@app.command(name="test")
def migration_test_cmd(
    rev: Annotated[str, typer.Argument(help="Revision id to test")],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    url: Annotated[str | None, typer.Option("--url")] = None,
    graph_name: Annotated[str | None, typer.Option("--graph")] = None,
) -> None:
    """Round-trip test a revision: upgrade → downgrade → upgrade (idempotency)."""
    from runic.config import Config
    from runic.context import MigrationContext
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    script_dir = ScriptDirectory.load(script_location)
    resolved = script_dir.get_revision(rev)
    rev_id = resolved.revision

    if url is not None:
        from falkordb import FalkorDB

        db = FalkorDB.from_url(url)
        source_graph_name = graph_name or "test"
    else:
        _exec_env(config)
        from runic.context import get as _get_ctx

        existing_ctx = _get_ctx()
        db = existing_ctx._db  # noqa: SLF001
        source_graph_name = existing_ctx._graph_name  # noqa: SLF001

    token = secrets.token_hex(4)
    ephemeral_name = f"{source_graph_name}__test_{rev_id}_{token}"
    ephemeral_graph = db.select_graph(ephemeral_name)

    cfg = Config(script_location=script_location)
    ctx = MigrationContext(cfg, db, ephemeral_graph)

    sep = "─" * 45
    typer.echo(f"runic test {rev_id}")
    typer.echo(sep)

    passed = True
    try:
        # Phase A — upgrade
        try:
            ctx.upgrade(target=rev_id)
            nodes_a = _entity_count(ephemeral_graph)
            idx_a = _index_count(ephemeral_graph)
            con_a = _constraint_count(ephemeral_graph)
            typer.echo(
                f"Phase A (upgrade):    ✓  nodes={nodes_a}  indices={idx_a}  constraints={con_a}"
            )
        except Exception as exc:
            typer.echo(f"Phase A (upgrade):    ✗  {exc}", err=True)
            passed = False
            raise

        # Phase B — downgrade
        try:
            ctx.downgrade(target="base")
            nodes_b = _entity_count(ephemeral_graph)
            idx_b = _index_count(ephemeral_graph)
            con_b = _constraint_count(ephemeral_graph)
            typer.echo(
                f"Phase B (downgrade):  ✓  nodes={nodes_b}  indices={idx_b}  constraints={con_b}"
            )
        except Exception as exc:
            typer.echo(f"Phase B (downgrade):  ✗  {exc}", err=True)
            passed = False
            raise

        # Phase C — idempotency (re-upgrade)
        try:
            ctx.upgrade(target=rev_id)
            nodes_c = _entity_count(ephemeral_graph)
            idx_c = _index_count(ephemeral_graph)
            con_c = _constraint_count(ephemeral_graph)
            typer.echo(
                f"Phase C (idempotency):✓  nodes={nodes_c}  indices={idx_c}  constraints={con_c}"
            )
        except Exception as exc:
            typer.echo(f"Phase C (idempotency):✗  {exc}", err=True)
            passed = False
            raise

    finally:
        with contextlib.suppress(Exception):
            ephemeral_graph.delete()

    typer.echo(sep)
    if passed:
        typer.echo("PASSED")
    else:
        typer.echo("FAILED", err=True)
        raise typer.Exit(code=1)
