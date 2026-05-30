import logging
from pathlib import Path
from typing import Annotated

import typer

log = logging.getLogger(__name__)

app = typer.Typer(name="runic", help="FalkorDB migration tool", no_args_is_help=True)

_DEFAULT_CONFIG = Path("runic/env.py")


def _exec_env(config: Path, preview: bool = False) -> None:
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


@app.command()
def init(
    directory: Annotated[
        Path, typer.Argument(help="Migration directory to scaffold")
    ] = Path("runic"),
    force: Annotated[bool, typer.Option("--force", help="Overwrite if exists")] = False,
) -> None:
    """Scaffold a new runic migration environment."""
    if directory.exists() and not force:
        typer.echo(
            f"Error: {directory} already exists. Use --force to overwrite.", err=True
        )
        raise typer.Exit(code=1)

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "versions").mkdir(exist_ok=True)
    (directory / "versions" / ".gitkeep").touch()

    templates_dir = Path(__file__).parent / "templates"
    (directory / "env.py").write_text((templates_dir / "env.py.mako").read_text())
    (directory / "script.py.mako").write_bytes(
        (templates_dir / "script.py.mako").read_bytes()
    )

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
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    sd = ScriptDirectory.load(script_location)
    resolved_head = head or sd.head()
    path = sd.create(message, resolved_head, script_location)
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
