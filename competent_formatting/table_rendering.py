"""Compile one generated table on its own -- to look at it, or to check that it fits.

`latex_table` writes a bare `tabular`, which tells you nothing about how it will behave inside
a real document: whether a macro it uses is defined, and above all whether it fits the text
width. Six value columns overflow a REVTeX column silently -- LaTeX reports an overfull box in
the log and carries on producing a PDF with the table running off the page.

So there are two jobs here, and they want the same wrapper:

* **preview** -- render the table in a plausible document and keep the PDF to look at. This is
  what `cf_quick_table_view` does.
* **check** -- render it against the *actual* document class and packages of the manuscript it
  is destined for, and report every LaTeX error and overfull box. `render_table` returns those
  rather than printing them, so a build script can gate on them.

Both go through `wrap_table_into_test_tex`, which is parameterised by document class, packages,
extra preamble and table environment: the defaults reproduce the historical JCTC/`achemso`
preview, and a RevTeX manuscript passes its own.
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .processing.latex_build import (  # noqa: F401  (re-exported: callers catch this one)
    PDFLATEX_COMMAND,
    PDFLaTeXMissingError,
    parse_log,
)
from .str_formatting import replace_special_LaTeX_symbols

# The historical preview target. Kept as the default so `cf_quick_table_view` behaves as it
# always has for callers that pass nothing.
DEFAULT_DOCUMENTCLASS = "[journal=jctc,manuscript=article,layout=traditional]{achemso}"
DEFAULT_PACKAGES = ("multirow,tabularx", "booktabs")

# `table` is the single-column float. A table too wide for it wants `table*` (both columns) or
# `sidewaystable` (rotated, needs the `rotating` package) -- which is a decision about the
# manuscript, so it is an argument rather than something guessed here.
DEFAULT_TABLE_ENVIRONMENT = "table"


def newcommands_from_replacements(replacements):
    """`'a:\\mathrm{A},b:\\mathrm{B}'` -> the matching `\\newcommand` lines.

    The tables often use macros the manuscript defines; without them the preview fails on an
    undefined control sequence rather than showing the table.
    """
    if not replacements:
        return ""
    lines = ""
    for replacement in replacements.split(","):
        name, value = replacement.split(":")
        lines += "\\newcommand{" + name + "}{" + value + "}\n"
    return lines


def _input_path(table_source_file):
    # \input takes the path without the .tex extension; absolute so the document compiles from
    # any working directory, including a temporary one.
    return os.path.splitext(os.path.abspath(table_source_file))[0]


def wrap_table_into_test_tex(
    table_source_file,
    pdf_title=None,
    newcommands="",
    documentclass=DEFAULT_DOCUMENTCLASS,
    packages=DEFAULT_PACKAGES,
    preamble="",
    table_environment=DEFAULT_TABLE_ENVIRONMENT,
    adjustbox=False,
):
    """A minimal document containing just this table.

    `documentclass` is everything after `\\documentclass`, options included. `packages` are
    `\\usepackage` arguments; `preamble` is spliced in verbatim after them, for anything that
    is not a plain package line. `adjustbox` wraps the table in
    `\\begin{adjustbox}{max width=\\textwidth,center}`, which shrinks an over-wide table to fit
    -- the usual remedy, and worth testing separately from the unwrapped width.
    """
    if pdf_title is None:
        pdf_title = "Displaying table: " + replace_special_LaTeX_symbols(
            os.path.basename(table_source_file)
        )

    package_lines = "".join("\\usepackage{" + package + "}\n" for package in packages)
    if adjustbox and not any(package.split(",")[0].strip() == "adjustbox" for package in packages):
        package_lines += "\\usepackage{adjustbox}\n"

    body = "\\input{" + _input_path(table_source_file) + "}\n"
    if adjustbox:
        body = "\\begin{adjustbox}{max width=\\textwidth,center}\n" + body + "\\end{adjustbox}\n"

    return (
        "\\documentclass"
        + documentclass
        + "\n"
        + package_lines
        + "\n"
        + newcommands
        + preamble
        + "\n\\title{"
        + pdf_title
        + "}\n\n\\begin{document}\n\\maketitle\n\n\\begin{"
        + table_environment
        + "}\n"
        + body
        + "\\end{"
        + table_environment
        + "}\n\\end{document}\n"
    )


@dataclass
class TableRenderResult:
    """What one pdflatex run said about a table."""

    table_source_file: str
    returncode: int
    log: str = ""
    pdf_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    overfull_pt: List[float] = field(default_factory=list)

    @property
    def compiled(self):
        return not self.errors and self.returncode == 0

    @property
    def fits(self):
        """True when nothing ran past the text width.

        Separate from `compiled` on purpose: an overfull table still produces a PDF, which is
        exactly why these go unnoticed.
        """
        return not self.overfull_pt

    @property
    def worst_overfull_pt(self):
        return max(self.overfull_pt) if self.overfull_pt else 0.0

    def summary(self):
        if self.errors:
            return "; ".join(self.errors)
        if self.overfull_pt:
            return f"{self.worst_overfull_pt:.0f}pt too wide"
        return "ok"


def render_table(table_source_file, out_dir=None, job_name=None, **wrap_kwargs):
    """Compile `table_source_file` on its own and report what LaTeX said.

    With `out_dir` the wrapper document and its PDF are written there and kept (the preview
    case); without it everything happens in a temporary directory that is removed, so only the
    parsed result survives (the checking case).

    Never raises on a LaTeX failure -- a failed compile is a result, not an exception. Only a
    missing pdflatex raises.
    """
    if shutil.which(PDFLATEX_COMMAND) is None:
        raise PDFLaTeXMissingError(f"{PDFLATEX_COMMAND} should be installed!")

    if job_name is None:
        job_name = "test_table_" + os.path.splitext(os.path.basename(table_source_file))[0]
    source = wrap_table_into_test_tex(table_source_file, **wrap_kwargs)

    keep = out_dir is not None
    workdir = out_dir if keep else tempfile.mkdtemp(prefix="cf_table_render_")
    try:
        os.makedirs(workdir, exist_ok=True)
        wrapper_path = os.path.join(workdir, job_name + ".tex")
        with open(wrapper_path, "w") as f:
            f.write(source)

        process = subprocess.run(
            [PDFLATEX_COMMAND, "-interaction=nonstopmode", job_name + ".tex"],
            cwd=workdir,
            capture_output=True,
            text=True,
            errors="replace",
        )

        log_path = os.path.join(workdir, job_name + ".log")
        log = ""
        if os.path.isfile(log_path):
            with open(log_path, "r", errors="replace") as f:
                log = f.read()
        # pdflatex writes its diagnostics to the log; stdout is the fallback when the run died
        # before the log existed.
        parsed = log or process.stdout

        pdf_path = os.path.join(workdir, job_name + ".pdf")
        summary = parse_log(parsed)
        return TableRenderResult(
            table_source_file=table_source_file,
            returncode=process.returncode,
            log=parsed,
            pdf_path=pdf_path if (keep and os.path.isfile(pdf_path)) else None,
            errors=summary.errors,
            overfull_pt=summary.overfull_pt,
        )
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)


def check_table_fits(table_source_file, **wrap_kwargs):
    """`(status, result)` where status is "ok", "needs adjustbox", or "failed".

    "needs adjustbox" means the table is too wide on its own but fits once wrapped in
    `\\begin{adjustbox}{max width=\\textwidth,center}` -- a one-line change in the manuscript
    rather than a broken table, so it is worth distinguishing from a real failure.
    """
    result = render_table(table_source_file, **wrap_kwargs)
    if not result.compiled:
        return "failed", result
    if result.fits:
        return "ok", result

    wrapped = render_table(table_source_file, adjustbox=True, **wrap_kwargs)
    if wrapped.compiled and wrapped.fits:
        return "needs adjustbox", result
    return "failed", result


def render_tables(table_source_files: Sequence[str], **wrap_kwargs):
    """`[(path, status, result), ...]` for several tables, in the order given."""
    return [(path, *check_table_fits(path, **wrap_kwargs)) for path in table_source_files]
