from __future__ import annotations

import contextlib
import logging
import secrets
from functools import wraps
from pathlib import Path
from typing import Annotated, Any

import typer

log = logging.getLogger(__name__)

app = typer.Typer(
    name="runic",
    help="FalkorDB migration tool",
    no_args_is_help=True,
    add_completion=True,
)

_DEFAULT_CONFIG = Path("runic/env.py")
_MARKER_FILE = Path(".runic")


def _resolve_config(config: Path) -> Path:
    """Return *config* as-is when it exists; otherwise check the .runic marker file.

    The .runic fallback only fires when the DEFAULT config path is in use.
    An explicit --config that does not exist is returned unchanged so callers
    can emit a meaningful "not found" error.
    """
    if config.exists():
        return config
    if config == _DEFAULT_CONFIG and _MARKER_FILE.exists():
        candidate = Path(_MARKER_FILE.read_text().strip())
        if candidate.exists():
            log.debug("resolved config from .runic: %s", candidate)
            return candidate
    return config


_DB_CONNECTION_ERROR_NAMES = frozenset(
    {"AuthenticationError", "ConnectionError", "TimeoutError"}
)


def _exec_env(config: Path, preview: bool = False) -> dict:  # noqa: ARG001
    config = _resolve_config(config)
    if not config.exists():
        typer.echo(
            f"Error: config not found at {config}. "
            "Run `runic init` first, or pass --config <dir>/env.py.",
            err=True,
        )
        raise typer.Exit(code=1)

    import runic.context as _ctx_module

    _orig_configure = _ctx_module.configure

    @wraps(_orig_configure)
    def _patched_configure(
        adapter: object, script_location: object = None, **kwargs: object
    ) -> None:
        kwargs.setdefault("_env_path", config)
        return _orig_configure(adapter, script_location, **kwargs)  # type: ignore[arg-type]

    _ctx_module.configure = _patched_configure  # type: ignore[assignment]
    namespace: dict = {"__file__": str(config), "__name__": "__main__"}
    try:
        exec(config.read_text(), namespace)  # noqa: S102
    except SystemExit, KeyboardInterrupt, typer.Exit:
        raise
    except Exception as exc:
        if type(exc).__name__ in _DB_CONNECTION_ERROR_NAMES or isinstance(
            exc, ConnectionRefusedError
        ):
            typer.echo(f"Error: database connection failed — {exc}", err=True)
            typer.echo(
                "  Check FALKORDB_URL (and FALKORDB_USERNAME / FALKORDB_PASSWORD if auth is required).",
                err=True,
            )
            raise typer.Exit(code=1) from exc
        raise
    return namespace


def _get_revision_config(config: Path) -> tuple[int, str | None]:
    """Read truncate_slug_length and file_template from env.py without requiring DB.

    Connection errors are silently dropped so that `runic revision` stays
    fully offline when the database is unavailable.
    """
    resolved = _resolve_config(config)
    if not resolved.exists():
        return 40, None
    namespace: dict = {"__file__": str(resolved), "__name__": "__main__"}
    try:
        exec(resolved.read_text(), namespace)  # noqa: S102
    except SystemExit, KeyboardInterrupt, typer.Exit:
        raise
    except ConnectionError, ConnectionRefusedError, OSError:
        log.debug(
            "connection error reading revision config from env.py — using defaults"
        )
    except Exception as exc:
        if type(exc).__name__ in _DB_CONNECTION_ERROR_NAMES:
            log.debug(
                "connection error reading revision config from env.py — using defaults"
            )
        else:
            raise
    return (
        int(namespace.get("truncate_slug_length", 40)),
        namespace.get("file_template") or None,
    )


def _get_script_location(config: Path) -> Path:
    return _resolve_config(config).parent


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
    from runic.service import init as _init

    try:
        _init(directory, force=force)
    except FileExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Created runic environment at {directory}/")
    typer.echo(f"  {directory}/env.py")
    typer.echo(f"  {directory}/script.py.mako")
    typer.echo(f"  {directory}/versions/")

    if (directory / "env.py") != _DEFAULT_CONFIG:
        _MARKER_FILE.write_text(str(directory / "env.py") + "\n")
        typer.echo(f"  {_MARKER_FILE}  (config pointer — commit this file)")


@app.command()
def revision(
    message: Annotated[
        str, typer.Option("-m", "--message", help="Short description of this revision")
    ],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    head: Annotated[str | None, typer.Option("--head")] = None,
    rev_id: Annotated[str | None, typer.Option("--rev-id")] = None,
    branch_label: Annotated[str | None, typer.Option("--branch-label")] = None,
    depends_on: Annotated[list[str], typer.Option("--depends-on")] = [],  # noqa: B006
    autogenerate: Annotated[bool, typer.Option("--autogenerate")] = False,
    format_: Annotated[bool, typer.Option("--format")] = False,
) -> None:
    """Create a new migration revision script."""
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)

    if autogenerate:
        env_ns = _exec_env(config)
        from runic import autogen
        from runic.context import get as _get_ctx

        ctx = _get_ctx()
        if ctx.target_manifest is None:
            typer.echo(
                "Error: --autogenerate requires target_manifest to be set in env.py",
                err=True,
            )
            raise typer.Exit(code=1)
        live = ctx.adapter.read_live_schema()
        ops = autogen.diff_schema(ctx.target_manifest, live)
        if not ops:
            typer.echo("No schema changes detected.")
            raise typer.Exit(code=0)
        upgrade_body = autogen.render_upgrade_body(ops)
        downgrade_body = autogen.render_downgrade_body(ops)
        trunc = int(env_ns.get("truncate_slug_length", 40))
        tmpl = env_ns.get("file_template") or None
        sd = ScriptDirectory.load(script_location)
        path = sd.create(
            message,
            sd.head(),
            script_location,
            branch_labels=[branch_label] if branch_label else None,
            depends_on=list(depends_on) or None,
            upgrade_body=upgrade_body,
            downgrade_body=downgrade_body,
            rev_id=rev_id,
            truncate_slug_length=trunc,
            file_template=tmpl,
        )
        typer.echo(f"Created revision: {path}  [CANDIDATE — review before applying]")
    else:
        trunc, tmpl = _get_revision_config(config)
        sd = ScriptDirectory.load(script_location)
        resolved_head = head if head is not None else sd.head()
        path = sd.create(
            message,
            resolved_head,
            script_location,
            branch_labels=[branch_label] if branch_label else None,
            depends_on=list(depends_on) or None,
            rev_id=rev_id,
            truncate_slug_length=trunc,
            file_template=tmpl,
        )
        typer.echo(f"Created revision: {path}")

    if format_:
        import subprocess

        try:
            subprocess.run(  # noqa: S603
                ["ruff", "format", str(path)],  # noqa: S607
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError, FileNotFoundError:
            log.warning("ruff format failed or ruff not installed; skipping")


@app.command()
def upgrade(
    target: Annotated[str, typer.Argument()] = "head",
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    preview: Annotated[bool, typer.Option("--preview")] = False,
    validate_on_migrate: Annotated[
        bool,
        typer.Option(
            "--validate-on-migrate",
            help="Abort if any already-applied script has a checksum mismatch",
        ),
    ] = False,
    installed_by: Annotated[
        str | None,
        typer.Option(
            "--installed-by", help="Attribution recorded with each applied revision"
        ),
    ] = None,
) -> None:
    """Apply migrations up to target (default: head)."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    if preview:
        ctx.enable_preview()

    ctx.upgrade(
        target, validate_on_migrate=validate_on_migrate, installed_by=installed_by
    )

    if preview and ctx.preview_log:
        for line in ctx.preview_log:
            typer.echo(line)
    elif preview:
        typer.echo("(no operations — nothing to upgrade)")
    else:
        current = ctx.current()
        typer.echo(f"Upgraded to: {current or target}")


@app.command()
def downgrade(
    target: Annotated[str, typer.Argument()] = "-1",
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    force: Annotated[bool, typer.Option("--force")] = False,
    preview: Annotated[bool, typer.Option("--preview")] = False,
) -> None:
    """Revert migrations down one step, or to TARGET revision / 'base'."""
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
        current = ctx.current()
        typer.echo(f"Downgraded to: {current or 'base'}")


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
    range_: Annotated[
        str | None, typer.Option("--range", help="Inclusive range start:end")
    ] = None,
) -> None:
    """Print all revisions chronologically (newest first), marking the applied revision as (head)."""
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    sd = ScriptDirectory.load(script_location)

    _exec_env(config)
    from runic.context import get

    current_rev = get().current()

    if range_:
        parts = range_.split(":")
        start = parts[0].strip() or None
        end = parts[1].strip() if len(parts) > 1 else None
        bp_set = {r.revision for r in sd.get_branch_points()}
        from runic.script import RevisionInfo

        items = list(
            reversed(
                [
                    RevisionInfo(
                        revision=r.revision,
                        down_revision=r.down_revision,
                        message=r.message,
                        create_date=r.create_date,
                        is_head=False,
                        is_branch_point=r.revision in bp_set,
                    )
                    for r in sd.walk_revisions(start, end, "up")
                ]
            )
        )
    else:
        items = list(reversed(sd.revision_history()))

    for info in items:
        tags = []
        if current_rev == info.revision:
            tags.append("head")

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
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    sd = ScriptDirectory.load(script_location)
    heads_list = sd.get_heads()

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
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    sd = ScriptDirectory.load(script_location)

    for bp in sd.get_branch_points():
        children = sd.get_children(bp.revision)
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
    from runic.script import RevisionNotFound, ScriptDirectory

    script_location = _get_script_location(config)
    sd = ScriptDirectory.load(script_location)

    try:
        revision = sd.get_revision(rev)
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


def _entity_count(adapter: Any) -> int:
    result = adapter.run_query(
        "MATCH (n) WHERE NOT n:_FalkorMigrateVersion RETURN count(n) AS c"
    )
    return int(result.result_set[0][0]) if result.result_set else 0


def _index_count(adapter: Any) -> int:
    result = adapter.run_query("CALL db.indexes() YIELD label RETURN count(label) AS c")
    return int(result.result_set[0][0]) if result.result_set else 0


def _constraint_count(adapter: Any) -> int:
    result = adapter.run_query(
        "CALL db.constraints() YIELD type RETURN count(type) AS c"
    )
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
    from runic.context import Runic
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    script_dir = ScriptDirectory.load(script_location)
    resolved = script_dir.get_revision(rev)
    rev_id = resolved.revision

    if url is not None:
        from runic.adapters.falkordb import FalkorDBAdapter

        base_adapter: Any = FalkorDBAdapter.from_url(url, graph_name or "test")
        source_graph_name = base_adapter.name
    else:
        _exec_env(config)
        from runic.context import get as _get_ctx

        existing_ctx = _get_ctx()
        base_adapter = existing_ctx.adapter
        source_graph_name = base_adapter.name

    token = secrets.token_hex(4)
    ephemeral_name = f"{source_graph_name}__test_{rev_id}_{token}"
    ephemeral_adapter = base_adapter.fork(ephemeral_name)

    ctx = Runic(ephemeral_adapter, script_location)

    sep = "─" * 45
    typer.echo(f"runic test {rev_id}")
    typer.echo(sep)

    passed = True
    try:
        # Phase A — upgrade
        try:
            ctx.upgrade(target=rev_id)
            nodes_a = _entity_count(ephemeral_adapter)
            idx_a = _index_count(ephemeral_adapter)
            con_a = _constraint_count(ephemeral_adapter)
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
            nodes_b = _entity_count(ephemeral_adapter)
            idx_b = _index_count(ephemeral_adapter)
            con_b = _constraint_count(ephemeral_adapter)
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
            nodes_c = _entity_count(ephemeral_adapter)
            idx_c = _index_count(ephemeral_adapter)
            con_c = _constraint_count(ephemeral_adapter)
            typer.echo(
                f"Phase C (idempotency):✓  nodes={nodes_c}  indices={idx_c}  constraints={con_c}"
            )
        except Exception as exc:
            typer.echo(f"Phase C (idempotency):✗  {exc}", err=True)
            passed = False
            raise

    finally:
        with contextlib.suppress(Exception):
            ephemeral_adapter.delete_graph()

    typer.echo(sep)
    if passed:
        typer.echo("PASSED")
    else:
        typer.echo("FAILED", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Phase 4 commands
# ---------------------------------------------------------------------------


@app.command(name="merge")
def merge_cmd(
    r1: Annotated[str, typer.Argument(help="First revision id or prefix")],
    r2: Annotated[str, typer.Argument(help="Second revision id or prefix")],
    message: Annotated[
        str, typer.Option("-m", "--message", help="Merge revision message")
    ],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    branch_label: Annotated[str | None, typer.Option("--branch-label")] = None,
) -> None:
    """Create a merge revision combining two branch heads."""
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    sd = ScriptDirectory.load(script_location)

    rev1 = sd.get_revision(r1)
    rev2 = sd.get_revision(r2)

    heads = {h.revision for h in sd.get_heads()}
    if rev1.revision not in heads or rev2.revision not in heads:
        typer.echo(
            f"Warning: {rev1.revision!r} or {rev2.revision!r} is not a current head",
            err=True,
        )

    path = sd.create(
        message,
        (rev1.revision, rev2.revision),
        script_location,
        branch_labels=[branch_label] if branch_label else None,
    )
    typer.echo(f"Created revision: {path}")


@app.command(name="validate")
def validate_cmd(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Check that applied migration scripts match their stored checksums."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    errors = ctx.validate()

    if not errors:
        typer.echo("All checksums valid.")
        return

    for err in errors:
        typer.echo(f"  x {err}", err=True)
    raise typer.Exit(code=1)


@app.command(name="run")
def run_cmd(
    scripts: Annotated[
        list[Path],
        typer.Argument(help=".py migration scripts to execute without recording"),
    ],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Execute migration script(s) against the database without recording in the chain."""
    _exec_env(config)
    from runic.context import get
    from runic.operations import GraphOperations
    from runic.script import _load_module

    ctx = get()
    ops = GraphOperations(ctx.adapter)

    for script in scripts:
        if not script.exists():
            typer.echo(f"Error: {script} not found", err=True)
            raise typer.Exit(code=1)
        if script.suffix != ".py":
            typer.echo(
                f"Error: {script.name} is not a .py file — only Python migration scripts are supported",
                err=True,
            )
            raise typer.Exit(code=1)
        mod = _load_module(script)
        if not hasattr(mod, "upgrade"):
            typer.echo(f"Error: {script.name} has no upgrade() function", err=True)
            raise typer.Exit(code=1)
        mod.upgrade(ops)
        typer.echo(f"Executed: {script.name}")


@app.command(name="info")
def info_cmd(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="COMPARE (default): pending vs applied | LOCAL: offline only | REMOTE: DB state only",
        ),
    ] = "COMPARE",
) -> None:
    """Show migration status. Modes: COMPARE (default), LOCAL, REMOTE."""
    mode = mode.upper()

    if mode == "LOCAL":
        from runic.script import ScriptDirectory

        sd = ScriptDirectory.load(_get_script_location(config))
        all_revs = sd.revision_history()
        heads = sd.get_heads()
        typer.echo(f"Local revisions : {len(all_revs)}")
        typer.echo(f"Heads           : {len(heads)}")
        for h in heads:
            typer.echo(f"  {h.revision}  {h.message}")
        return

    _exec_env(config)
    from runic.context import get

    ctx = get()
    current_revs = ctx._version_node.get()  # noqa: SLF001

    if mode == "REMOTE":
        if not current_revs:
            typer.echo("Applied : <none>")
        else:
            for rev_id in current_revs:
                msg = ctx.get_revision_message(rev_id) or ""
                label = f"{rev_id}  {msg}".strip()
                typer.echo(f"Applied : {label}")
        return

    # COMPARE (default)
    all_revs = ctx.get_history()
    try:
        pending = ctx._script_dir.topological_upgrade_path(  # noqa: SLF001
            current_revs or None, "head"
        )
    except Exception:
        pending = []

    applied_count = len(all_revs) - len(pending)

    if not current_revs:
        current_label = "<none>"
    elif len(current_revs) == 1:
        msg = ctx.get_revision_message(current_revs[0]) or ""
        current_label = f"{current_revs[0]}  {msg}".strip()
    else:
        current_label = f"{len(current_revs)} heads"

    typer.echo(f"Database : {ctx.adapter.name}")
    typer.echo(f"Current  : {current_label}")
    typer.echo(f"Applied  : {applied_count} of {len(all_revs)}")
    typer.echo(f"Pending  : {len(pending)}")

    if pending:
        typer.echo("\nPending migrations:")
        for rev in pending:
            typer.echo(f"  {rev.revision}  {rev.message}")


# ---------------------------------------------------------------------------
# Phase 2.5 — baseline command
# ---------------------------------------------------------------------------


@app.command()
def baseline(
    message: Annotated[
        str, typer.Option("-m", "--message", help="Revision message")
    ] = "baseline",
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    graph: Annotated[
        str | None,
        typer.Option("--graph", help="Override graph name from env config"),
    ] = None,
    stamp_only: Annotated[
        bool,
        typer.Option(
            "--stamp-only", help="Stamp the version node without writing a file"
        ),
    ] = False,
) -> None:
    """Generate an initial migration from a live graph's schema.

    Introspects the live graph, writes a root revision (down_revision=None)
    that recreates all indexes and constraints, and stamps the version node so
    Runic treats it as already applied.  Run on a fresh graph to reproduce the
    schema (e.g. in CI or when cloning a tenant).
    """
    _exec_env(config)
    from runic.context import get
    from runic.exceptions import GraphAlreadyManagedError

    ctx = get()

    if graph is not None:
        from runic.adapters.falkordb import FalkorDBAdapter
        from runic.operations import GraphOperations
        from runic.version import VersionNode

        old_adapter = ctx._adapter  # noqa: SLF001
        if isinstance(old_adapter, FalkorDBAdapter):
            new_adapter = old_adapter.fork(graph)
            ctx._adapter = new_adapter  # noqa: SLF001
            ctx._version_node = VersionNode(new_adapter)  # noqa: SLF001
            ctx._ops = GraphOperations(new_adapter)  # noqa: SLF001
        else:
            typer.echo(
                "Warning: --graph override is only supported for FalkorDB adapters; "
                "using configured graph name.",
                err=True,
            )

    try:
        file_path = ctx.baseline(message, stamp_only=stamp_only)
    except GraphAlreadyManagedError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    rev_id = ctx.current()

    if stamp_only:
        typer.echo(f"Stamped:   {rev_id}")
    else:
        typer.echo(f"Generated: {file_path}")
        typer.echo(f"Stamped:   {rev_id}")

    if not stamp_only:
        from runic.introspect import introspect_graph, render_manifest_code

        snapshot = introspect_graph(ctx._adapter._graph)  # noqa: SLF001
        manifest = render_manifest_code(snapshot)
        sep = "─" * 64
        typer.echo(
            "\nSchema manifest — paste into env.py and pass to "
            "context.configure(..., target_manifest=target_manifest) "
            "to enable `runic revision --autogenerate`:"
        )
        typer.echo(sep)
        typer.echo(manifest)
        typer.echo(sep)


@app.command(name="check")
def check_cmd(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Exit non-zero if the live schema has pending changes vs the manifest (CI gate)."""
    _exec_env(config)
    from runic import autogen
    from runic.context import get as _get_ctx

    ctx = _get_ctx()
    if ctx.target_manifest is None:
        typer.echo(
            "Error: check requires target_manifest to be set in env.py via "
            "context.configure(..., target_manifest=...)",
            err=True,
        )
        raise typer.Exit(code=1)

    live = ctx.adapter.read_live_schema()
    ops = autogen.diff_schema(ctx.target_manifest, live)

    if not ops:
        typer.echo("Schema up-to-date.")
        return

    typer.echo(
        'Pending schema changes (run `runic revision --autogenerate -m "..."` to generate):'
    )
    for op_item in ops:
        prefix = "+" if op_item.action == "create" else "-"
        typer.echo(f"  {prefix} {op_item.op_call}")
    raise typer.Exit(code=1)
