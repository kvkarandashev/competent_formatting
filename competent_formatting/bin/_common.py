"""Options and output shared by the source-processing commands.

``cf_macro_removal``, ``cf_flatten``, ``cf_jcp_source`` and ``cf_arxiv_source`` all strip the
same revision markup, so they take it with the same four repeatable options, and the two
packagers report their checks and exit codes the same way.
"""

import sys

import click

from ..processing.jcp_checks import INFO
from ..processing.latex_build import MissingExecutableError
from ..processing.source_package import Markup, SourcePackageError, SourcePackageUsageError

MARKUP_OPTIONS = (
    click.option(
        "--opened_macro",
        multiple=True,
        help="Revision macro whose content is kept: \\NAME{text} -> text. Repeatable.",
    ),
    click.option(
        "--removed_macro",
        multiple=True,
        help="Comment macro dropped with its content: \\NAME{text} -> ''. Repeatable.",
    ),
    click.option(
        "--opened_env",
        multiple=True,
        help="Revision environment whose body is kept: \\begin{NAME}x\\end{NAME} -> x. "
        "Repeatable.",
    ),
    click.option(
        "--removed_env", multiple=True, help="Environment dropped with its body. Repeatable."
    ),
)


def markup_options(function):
    for option in reversed(MARKUP_OPTIONS):
        function = option(function)
    return function


def markup_from(opened_macro=(), removed_macro=(), opened_env=(), removed_env=()):
    return Markup(tuple(opened_macro), tuple(removed_macro), tuple(opened_env), tuple(removed_env))


def write_output(text, output):
    """Write to ``output``, or to stdout when it is ``None`` or ``-``."""
    if output in (None, "-"):
        click.echo(text, nl=False)
        return
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(text)


def exit_on_leftovers(leftovers):
    """Markup the stripper did not recognise is an error: the output would still carry it."""
    if not leftovers:
        return
    for leftover in leftovers:
        click.echo(
            f"[error] markup: {leftover} still appears after cleaning; it is probably used in a "
            "way the stripper did not recognise (check for an unbalanced brace)",
            err=True,
        )
    sys.exit(1)


def run_packager(build, strict):
    """Call ``build()`` and report its result the way every packager does.

    Exits 2 on a usage error, 1 on a hard failure (or a warning under ``--strict``).
    """
    try:
        result = build()
    except (SourcePackageUsageError, MissingExecutableError) as error:
        click.echo(str(error), err=True)
        sys.exit(2)
    except SourcePackageError as error:
        click.echo(str(error), err=True)
        sys.exit(1)

    for check in result.checks:
        if check.level != INFO:
            click.echo(check.render())
    click.echo("")
    click.echo(f"wrote {result.out_dir}")
    click.echo(f"  report: {result.report_path}")

    failures = len(result.hard_failures)
    warnings = len(result.warnings)
    click.echo(f"{failures} hard failure(s), {warnings} warning(s)")
    if failures:
        sys.exit(1)
    if strict and warnings:
        click.echo("--strict: warnings count as failures", err=True)
        sys.exit(1)
    return result
