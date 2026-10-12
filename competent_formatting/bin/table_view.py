"""``cf_quick_table_view``: compile one generated table on its own and look at it."""

import os
import sys

import click

from ..table_rendering import (
    DEFAULT_DOCUMENTCLASS,
    DEFAULT_PACKAGES,
    DEFAULT_TABLE_ENVIRONMENT,
    PDFLaTeXMissingError,
    check_table_fits,
    newcommands_from_replacements,
    render_table,
)


@click.command()
@click.argument("filename")
@click.option(
    "--replacements",
    default=None,
    help="specifying comma-separated replacement string (e.g. 'a:\\mathrm{A},b:\\mathrm{B}') will "
    "result in the corresponding replacements being performed in the final PDF via addition of "
    "'\\newcommand' lines",
)
@click.option(
    "--documentclass",
    default=DEFAULT_DOCUMENTCLASS,
    help="everything after \\documentclass, options included; default is the JCTC achemso class. "
    "Pass the manuscript's own to see the table at its real width.",
)
@click.option(
    "--package",
    "packages",
    multiple=True,
    help="a \\usepackage argument; repeatable. Replaces the default set when given.",
)
@click.option(
    "--preamble_file",
    default=None,
    help="file whose contents are spliced into the preamble verbatim, for macro definitions "
    "and anything that is not a plain \\usepackage line.",
)
@click.option(
    "--table_environment",
    default=DEFAULT_TABLE_ENVIRONMENT,
    help="float to put the table in: 'table' (one column), 'table*' (both), 'sidewaystable'.",
)
@click.option(
    "--adjustbox",
    is_flag=True,
    help="wrap the table in \\begin{adjustbox}{max width=\\textwidth,center}, which shrinks an "
    "over-wide table to fit.",
)
@click.option(
    "--check",
    is_flag=True,
    help="report only, keeping no PDF, and exit non-zero if the table does not typeset or does "
    "not fit the text width.",
)
def main(
    filename,
    replacements,
    documentclass,
    packages,
    preamble_file,
    table_environment,
    adjustbox,
    check,
):
    """
    Generate a PDF embedding the table created with `competent_formatting.tables` output, with
    `FILENAME` defining input TeX file.

    An overfull table still produces a PDF, so the width is reported either way: LaTeX does not
    treat "runs off the page" as an error and neither run would otherwise tell you.
    """
    if os.path.splitext(filename)[1] != ".tex":
        click.echo("Tex filename must end with '.tex'!", err=True)
        sys.exit(1)

    preamble = ""
    if preamble_file is not None:
        with open(preamble_file, "r") as f:
            preamble = f.read()

    wrap_kwargs = {
        "newcommands": newcommands_from_replacements(replacements),
        "documentclass": documentclass,
        "packages": packages if packages else DEFAULT_PACKAGES,
        "preamble": preamble,
        "table_environment": table_environment,
    }

    try:
        if check:
            status, result = check_table_fits(filename, **wrap_kwargs)
        else:
            # The preview writes beside the table, as it always has, so the PDF is there to open.
            result = render_table(
                filename,
                out_dir=os.path.dirname(os.path.abspath(filename)),
                adjustbox=adjustbox,
                **wrap_kwargs,
            )
            status = "ok" if result.compiled and result.fits else None
    except PDFLaTeXMissingError as error:
        click.echo(str(error), err=True)
        sys.exit(1)

    for error in result.errors:
        click.echo(f"LaTeX error: {error}", err=True)
    if not result.fits:
        click.echo(
            f"{result.worst_overfull_pt:.0f}pt too wide for {table_environment} in this class",
            err=True,
        )

    if check:
        click.echo(f"{status}: {filename}")
        if status == "needs adjustbox":
            click.echo(
                "  fits inside \\begin{adjustbox}{max width=\\textwidth,center}; add that "
                "around the \\input in the manuscript"
            )
        sys.exit(0 if status == "ok" else 1)

    if result.pdf_path is not None:
        click.echo(f"wrote {result.pdf_path}")
    elif not result.compiled:
        sys.exit(1)
