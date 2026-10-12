"""Rendering a generated table on its own, for preview or for a width check."""

import shutil

import pytest

from competent_formatting.table_rendering import (
    DEFAULT_DOCUMENTCLASS,
    check_table_fits,
    newcommands_from_replacements,
    render_table,
    wrap_table_into_test_tex,
)
from competent_formatting.tables import latex_table

pdflatex_required = pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex is not installed"
)


def write_table(tmp_path, n_columns, name="table.tex"):
    """A table of `n_columns` wide cells, so the width can be dialled up and down."""
    rows = [["row"] + [f"col {index}" for index in range(n_columns)]]
    rows.append(["value"] + [(1.2345, 0.0678)] * n_columns)
    path = tmp_path / name
    path.write_text(latex_table(rows, column_types="l" + "c" * n_columns))
    return str(path)


# ----------------------------------------------------------------------------------
# The wrapper document
# ----------------------------------------------------------------------------------


def test_defaults_reproduce_the_historical_preview(tmp_path):
    source = wrap_table_into_test_tex(write_table(tmp_path, 2))
    assert DEFAULT_DOCUMENTCLASS in source
    assert "\\usepackage{multirow,tabularx}" in source
    assert "\\usepackage{booktabs}" in source
    assert "\\begin{table}" in source and "\\begin{table*}" not in source


def test_document_class_packages_and_preamble_are_parameterised(tmp_path):
    source = wrap_table_into_test_tex(
        write_table(tmp_path, 2),
        documentclass="[aip,jcp,preprint]{revtex4-2}",
        packages=["booktabs", "multirow"],
        preamble="\\newcommand{\\Ntrain}{N}\n",
        table_environment="table*",
    )
    assert "\\documentclass[aip,jcp,preprint]{revtex4-2}" in source
    assert "\\usepackage{tabularx}" not in source  # the defaults were replaced, not extended
    assert "\\newcommand{\\Ntrain}{N}" in source
    assert "\\begin{table*}" in source and "\\end{table*}" in source


def test_input_path_is_absolute_and_extensionless(tmp_path):
    path = write_table(tmp_path, 2)
    source = wrap_table_into_test_tex(path)
    assert "\\input{" + path[: -len(".tex")] + "}" in source


def test_adjustbox_wraps_and_pulls_in_its_package(tmp_path):
    source = wrap_table_into_test_tex(write_table(tmp_path, 2), adjustbox=True)
    assert "\\usepackage{adjustbox}" in source
    assert "\\begin{adjustbox}{max width=\\textwidth,center}" in source
    assert "\\end{adjustbox}" in source


def test_adjustbox_package_is_not_added_twice(tmp_path):
    source = wrap_table_into_test_tex(
        write_table(tmp_path, 2), packages=["adjustbox", "booktabs"], adjustbox=True
    )
    assert source.count("\\usepackage{adjustbox}") == 1


def test_newcommands_from_replacements():
    assert newcommands_from_replacements(None) == ""
    assert newcommands_from_replacements("") == ""
    assert newcommands_from_replacements("a:\\mathrm{A},b:\\mathrm{B}") == (
        "\\newcommand{a}{\\mathrm{A}}\n\\newcommand{b}{\\mathrm{B}}\n"
    )


# ----------------------------------------------------------------------------------
# Compiling
# ----------------------------------------------------------------------------------


@pdflatex_required
def test_narrow_table_compiles_and_fits(tmp_path):
    result = render_table(write_table(tmp_path, 2))
    assert result.compiled
    assert result.fits
    assert result.summary() == "ok"


@pdflatex_required
def test_overfull_table_still_compiles_but_does_not_fit(tmp_path):
    """The failure mode this exists to catch: a PDF is produced regardless."""
    result = render_table(write_table(tmp_path, 14))
    assert result.compiled, "an over-wide table is not a LaTeX error"
    assert not result.fits
    assert result.worst_overfull_pt > 0.0
    assert "too wide" in result.summary()


@pdflatex_required
def test_temporary_workdir_leaves_nothing_behind(tmp_path):
    table = write_table(tmp_path, 2)
    render_table(table)
    # Only the table itself; no wrapper, log, aux or PDF.
    assert [path.name for path in tmp_path.iterdir()] == ["table.tex"]


@pdflatex_required
def test_out_dir_keeps_the_pdf(tmp_path):
    out_dir = tmp_path / "out"
    result = render_table(write_table(tmp_path, 2), out_dir=str(out_dir))
    assert result.pdf_path is not None
    assert (out_dir / "test_table_table.pdf").is_file()


@pdflatex_required
def test_check_table_fits_statuses(tmp_path):
    status, _ = check_table_fits(write_table(tmp_path, 2, name="narrow.tex"))
    assert status == "ok"

    # Wide enough to overflow the column, but not so wide that shrinking cannot save it.
    status, result = check_table_fits(write_table(tmp_path, 14, name="wide.tex"))
    assert status == "needs adjustbox"
    assert result.worst_overfull_pt > 0.0


@pdflatex_required
def test_wider_float_fixes_a_table_that_overflows_one_column(tmp_path):
    # Wide enough to overflow a single REVTeX column, narrow enough for the full-width float.
    table = write_table(tmp_path, 5)
    narrow = render_table(
        table,
        documentclass="[aip,jcp,twocolumn]{revtex4-2}",
        packages=["booktabs", "multirow"],
        table_environment="table",
    )
    wide = render_table(
        table,
        documentclass="[aip,jcp,twocolumn]{revtex4-2}",
        packages=["booktabs", "multirow"],
        table_environment="table*",
    )
    assert not narrow.fits
    assert wide.fits
