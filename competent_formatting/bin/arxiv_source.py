"""``cf_arxiv_source``: turn one or more documents into an arXiv-ready source directory."""

import click

from ..processing.arxiv_source import build_arxiv_source
from ._common import markup_from, markup_options, run_packager


@click.command()
@click.argument("tex_files", nargs=-1, required=True)
@click.option(
    "--out",
    default="./arxiv_submission",
    help="Output directory. Must not be the manuscript directory or a parent of it.",
)
@markup_options
@click.option(
    "--bbl",
    type=click.Choice(["inline", "separate"]),
    default="inline",
    help="inline: splice each .bbl into its .tex. separate: ship <stem>.bbl beside it.",
)
@click.option(
    "--keep_comments",
    is_flag=True,
    help="Keep %-comments. They are stripped by default: arXiv serves the source publicly.",
)
@click.option(
    "--figure_prefix",
    multiple=True,
    help="Stem for the renamed figures, once per TEX_FILE in the same order. Default: 'fig' "
    "for the first document, '<stem>_fig' for the others.",
)
@click.option(
    "--anc",
    multiple=True,
    help="File or directory shipped as an ancillary file under anc/. Repeatable.",
)
@click.option(
    "--ascii", is_flag=True, help="Also replace non-ASCII characters with LaTeX commands."
)
@click.option(
    "--readme/--no-readme",
    "write_readme",
    default=True,
    help="Write 00README.json naming the TEX_FILES as top-level files, in order.",
)
@click.option("--zip/--no-zip", "make_archive", default=True, help="Write source.zip as well.")
@click.option("--strict", is_flag=True, help="Treat warnings as failures.")
@click.option("--force", is_flag=True, help="Replace the contents of a non-empty --out.")
def main(
    tex_files,
    out,
    opened_macro,
    removed_macro,
    opened_env,
    removed_env,
    bbl,
    keep_comments,
    figure_prefix,
    anc,
    ascii,
    write_readme,
    make_archive,
    strict,
    force,
):
    """Package TEX_FILES (top-level documents, in PDF order) as one arXiv upload.

    Each document is flattened, cleaned of the named revision markup and of comments, given
    its bibliography from a BibTeX build, and has its figures renamed beside it. An
    \\externaldocument pointing at another packaged document is replaced by that document's
    labels, since arXiv compiles each top-level file on its own. The result is verified by
    compiling `source/` in an empty directory with pdflatex alone; upload the contents of
    `source/` (or source.zip). Exits 1 if a hard check failed, 2 on a usage error.
    """
    run_packager(
        lambda: build_arxiv_source(
            tex_files,
            out,
            markup=markup_from(opened_macro, removed_macro, opened_env, removed_env),
            bbl=bbl,
            keep_comments=keep_comments,
            figure_prefixes=figure_prefix,
            anc=anc,
            ascii=ascii,
            write_readme=write_readme,
            make_archive=make_archive,
            force=force,
            log=lambda message: click.echo(f"  {message}"),
        ),
        strict,
    )
