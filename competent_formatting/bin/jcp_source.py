"""``cf_jcp_source``: package a manuscript for a J. Chem. Phys. source upload."""

import click

from ..processing.jcp_source import build_jcp_source
from ._common import markup_options, run_packager


@click.command()
@click.argument("main_tex")
@click.option(
    "--out",
    default="./jcp_submission",
    help="Output directory. Must not be the manuscript directory or a parent of it.",
)
@click.option("--si", default=None, help="Supplementary material .tex; built to a PDF only.")
@markup_options
@click.option(
    "--bbl",
    type=click.Choice(["inline", "separate"]),
    default="inline",
    help="inline: splice the .bbl into the .tex. separate: ship the .bbl as its own file.",
)
@click.option(
    "--keep_comments", is_flag=True, help="Keep %-comments (they are stripped by default)."
)
@click.option("--figure_prefix", default="fig", help="Stem for the renamed figures.")
@click.option(
    "--engine",
    default="pdflatex",
    help="Compilation engine. Only pdflatex is supported: it is what the package verifies against.",
)
@click.option(
    "--marked_pdf",
    is_flag=True,
    help="Also compile the uncleaned manuscript to <stem>_marked.pdf (changes highlighted), "
    "and with --si the uncleaned supplementary material to <si stem>_marked.pdf.",
)
@click.option("--zip/--no-zip", "make_archive", default=True, help="Write source.zip as well.")
@click.option("--strict", is_flag=True, help="Treat warnings as failures.")
@click.option("--force", is_flag=True, help="Replace the contents of a non-empty --out.")
def main(
    main_tex,
    out,
    si,
    opened_macro,
    removed_macro,
    opened_env,
    removed_env,
    bbl,
    keep_comments,
    figure_prefix,
    engine,
    marked_pdf,
    make_archive,
    strict,
    force,
):
    """Flatten MAIN_TEX into a self-contained source package, compile it in isolation, check it.

    The output directory holds what AIP's Peer X-Press upload wants: a flat `source/`
    directory, the author-generated PDF built from exactly those files, a draft alt-text file
    and a report. Exits 1 if a hard check failed, 2 on a usage error.
    """
    run_packager(
        lambda: build_jcp_source(
            main_tex,
            out,
            si=si,
            opened_macros=opened_macro,
            removed_macros=removed_macro,
            opened_envs=opened_env,
            removed_envs=removed_env,
            bbl=bbl,
            keep_comments=keep_comments,
            figure_prefix=figure_prefix,
            engine=engine,
            marked_pdf=marked_pdf,
            make_archive=make_archive,
            force=force,
            log=lambda message: click.echo(f"  {message}"),
        ),
        strict,
    )
