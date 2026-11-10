"""``cf_flatten``: inline every ``\\input``/``\\include`` of a LaTeX file into one text."""

import click

from ..processing.source_package import SourcePackageError, flatten_and_clean
from ._common import exit_on_leftovers, markup_from, markup_options, write_output


@click.command()
@click.argument("filename")
@click.option("--output", "-o", default=None, help="Write here instead of to stdout.")
@click.option(
    "--strip_comments",
    is_flag=True,
    help="Drop %-comments (lines are shortened or emptied, never joined).",
)
@markup_options
def main(filename, output, strip_comments, opened_macro, removed_macro, opened_env, removed_env):
    """Flatten FILENAME: inline its \\input/\\include files, recursively, as TeX would.

    Paths resolve against FILENAME's directory. Revision markup named with the markup options
    is stripped from the flattened text (see cf_macro_removal). Figures, bibliography and
    \\externaldocument are left as they are; cf_jcp_source and cf_arxiv_source handle those.
    """
    try:
        _, cleaned, leftovers = flatten_and_clean(
            filename,
            markup_from(opened_macro, removed_macro, opened_env, removed_env),
            keep_comments=not strip_comments,
        )
    except SourcePackageError as error:
        raise click.ClickException(str(error)) from error
    write_output(cleaned, output)
    exit_on_leftovers(leftovers)
