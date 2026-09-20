"""``cf_view``: a local web viewer that recompiles LaTeX documents on demand."""

import socket
import sys
import threading
import webbrowser
from pathlib import Path
from types import SimpleNamespace

import click
from click.core import ParameterSource

from ..viewer.defaults import DEFAULT_LATEX_CMD, LOCK_FILENAME, VIEW_EXTRA_HINT, WORKDIR_DIRNAME

EXPLICIT_KEYS = {
    "doc": "docs",
    "opened_macro": "opened_macros",
    "removed_macro": "removed_macros",
    "pre_script": "pre_scripts",
    "doc_pre_script": "doc_pre_scripts",
    "host": "host",
    "port": "port",
    "latex_cmd": "latex_cmd",
}


def import_viewer():
    """Import the parts that need the optional ``view`` dependencies.

    Done lazily so that ``cf_view --help`` works, and so that a missing extra
    reports what to install instead of an ImportError traceback.
    """
    try:
        from ..viewer.app import ViewerState, create_app
        from ..viewer.config import default_workdir, find_workdir, load_config, save_config
        from ..viewer.session import ReconciliationError, parse_labelled, reconcile, seed_config
    except ImportError as error:
        raise click.ClickException(f"{VIEW_EXTRA_HINT}\n\n(import failed: {error})")
    return SimpleNamespace(
        ViewerState=ViewerState,
        create_app=create_app,
        default_workdir=default_workdir,
        find_workdir=find_workdir,
        load_config=load_config,
        save_config=save_config,
        ReconciliationError=ReconciliationError,
        parse_labelled=parse_labelled,
        reconcile=reconcile,
        seed_config=seed_config,
    )


def free_port(host, start):
    """Return ``start``, or the first free port above it."""
    for candidate in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex((host, candidate)) != 0:
                return candidate
    return start


@click.command()
@click.option(
    "--workdir",
    default=None,
    help=f"Session directory. Default: the nearest {WORKDIR_DIRNAME} found by walking up from "
    f"the current directory, else a new {WORKDIR_DIRNAME} created here.",
)
@click.option(
    "--doc",
    "doc",
    multiple=True,
    help="Register a main .tex as [LABEL=]PATH; the label defaults to the file stem.",
)
@click.option(
    "--opened_macro",
    "opened_macro",
    multiple=True,
    help="Revision macro whose content is KEPT in the clean profile "
    "(e.g. 'revised': \\revised{text} -> text).",
)
@click.option(
    "--removed_macro",
    "removed_macro",
    multiple=True,
    help="Comment macro dropped with its content in the clean profile "
    "(e.g. 'collaboratorcomment': \\collaboratorcomment{note} -> '').",
)
@click.option(
    "--pre_script", "pre_script", multiple=True, help="Global pre-compile hook (shell command)."
)
@click.option(
    "--doc_pre_script",
    "doc_pre_script",
    multiple=True,
    help="Per-document pre-compile hook, as LABEL=COMMAND.",
)
@click.option(
    "--host", default="127.0.0.1", help="Bind address. See the security note in AGENTS.md."
)
@click.option(
    "--port", default=8000, type=int, help="Bind port; the first free port above is used."
)
@click.option(
    "--latex_cmd", default=DEFAULT_LATEX_CMD, help="Compile template; {main} is the tex file."
)
@click.option(
    "--open", "open_browser", is_flag=True, help="Open the viewer in a browser on start."
)
@click.option(
    "--overwrite_config",
    is_flag=True,
    help="Let explicitly-passed flags win over a contradicting persisted config.",
)
@click.option(
    "--dry_run", is_flag=True, help="Write/validate the config and exit without serving."
)
@click.pass_context
def main(
    ctx,
    workdir,
    doc,
    opened_macro,
    removed_macro,
    pre_script,
    doc_pre_script,
    host,
    port,
    latex_cmd,
    open_browser,
    overwrite_config,
    dry_run,
):
    """Serve a browser UI that displays and recompiles LaTeX documents.

    The workdir's competent_viewer.toml is the single source of truth: this
    command seeds it, the in-browser menu edits it, and a later run recovers the
    whole session from it.
    """
    viewer = import_viewer()
    if workdir is None:
        workdir_path = viewer.default_workdir()
        if viewer.find_workdir() is not None:
            click.echo(f"using session {workdir_path}")
    else:
        workdir_path = Path(workdir).expanduser().resolve()
    workdir_path.mkdir(parents=True, exist_ok=True)

    try:
        spec = {
            "docs": [viewer.parse_labelled(value, "--doc") for value in doc],
            "opened_macros": list(opened_macro),
            "removed_macros": list(removed_macro),
            "pre_scripts": list(pre_script),
            "doc_pre_scripts": [
                viewer.parse_labelled(value, "--doc_pre_script") for value in doc_pre_script
            ],
            "host": host,
            "port": port,
            "latex_cmd": latex_cmd,
        }
    except ValueError as error:
        raise click.ClickException(str(error))

    explicit = {
        key
        for name, key in EXPLICIT_KEYS.items()
        if ctx.get_parameter_source(name) is ParameterSource.COMMANDLINE
    }

    config = viewer.load_config(workdir_path)
    try:
        if config is None:
            if not spec["docs"]:
                raise click.ClickException(
                    "no documents registered yet -- pass at least one --doc [LABEL=]PATH"
                )
            config = viewer.seed_config(spec)
            viewer.save_config(workdir_path, config)
            click.echo(f"wrote {workdir_path / 'competent_viewer.toml'}")
        else:
            changes = viewer.reconcile(config, spec, explicit, overwrite=overwrite_config)
            if changes:
                viewer.save_config(workdir_path, config)
                click.echo("updated the session config:")
                for change in changes:
                    click.echo(f"  {change}")
            else:
                click.echo(f"recovered session from {workdir_path / 'competent_viewer.toml'}")
    except viewer.ReconciliationError as error:
        click.echo(error.render(), err=True)
        sys.exit(2)
    except ValueError as error:
        raise click.ClickException(str(error))

    if not config.documents:
        raise click.ClickException("the session has no documents; add one with --doc")

    if dry_run:
        click.echo("dry run: not starting the server")
        return

    bind_port = free_port(config.host, config.port)
    if bind_port != config.port:
        click.echo(f"port {config.port} is busy; serving on {bind_port}")

    lock_path = workdir_path / LOCK_FILENAME
    lock_path.write_text(str(bind_port), encoding="utf-8")

    state = viewer.ViewerState(workdir_path, config)
    app = viewer.create_app(state)

    url = f"http://{config.host}:{bind_port}/"
    click.echo(f"serving {len(config.documents)} document(s) at {url}")
    click.echo(f"  logs: {workdir_path / 'logs'}")
    click.echo(f"  builds: {workdir_path / 'build'}")
    if config.host != "127.0.0.1":
        click.echo(
            "  WARNING: recompiling runs your configured hooks, so this URL is remote code "
            "execution for anyone who can reach it. Prefer 'tailscale serve' over a wide bind.",
            err=True,
        )
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    import uvicorn

    try:
        uvicorn.run(app, host=config.host, port=bind_port, log_level="warning")
    finally:
        lock_path.unlink(missing_ok=True)
