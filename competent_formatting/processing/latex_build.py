"""Running LaTeX, and reading what it said.

Three callers need this and they used to answer it twice: the table renderer wants overfull
boxes, the viewer wants a build status, and the submission packager wants every error,
undefined reference and missing file. The parsing is the same parsing, so it lives here, and
the two rules worth stating once live here too:

* **A LaTeX run that failed is a result, not an exception.** Only a missing executable raises.
* **Exit codes do not decide success.** ``latexmk`` exits non-zero on a non-fatal BibTeX
  complaint and re-reports it on every later no-op run, so a healthy manuscript would read as
  permanently broken. What decides is whether the PDF on disk is at least as new as the
  inputs it was built from (:func:`build_status`).
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List

PDFLATEX_COMMAND = "pdflatex"
LATEXMK_COMMAND = "latexmk"
BIBTEX_COMMAND = "bibtex"
KPSEWHICH_COMMAND = "kpsewhich"
PDFFONTS_COMMAND = "pdffonts"

# pdflatex needs several passes before cross-references settle; four is what latexmk would
# do in the worst case for a document with a table of contents and \ref forward references.
MAX_PDFLATEX_RUNS = 4

_LATEX_ERROR = re.compile(r"^! (.+)$", re.MULTILINE)
_OVERFULL_HBOX = re.compile(r"^Overfull \\hbox \(([0-9.]+)pt too wide\)", re.MULTILINE)
_UNDEFINED_REFERENCE = re.compile(r"Reference `([^']*)' on page [0-9]+ undefined")
_UNDEFINED_CITATION = re.compile(r"Citation `([^']*)' on page [0-9]+ undefined")
_MISSING_FILE = re.compile(r"^(?:! )?(?:LaTeX Error: )?File `([^']*)' not found", re.MULTILINE)
_RERUN = re.compile(r"(Label\(s\) may have changed|Rerun to get|Please rerun)")
_UNDEFINED_SUMMARY = re.compile(r"There were undefined (references|citations)")


class MissingExecutableError(RuntimeError):
    """Raised instead of failing obscurely when a required program is not on PATH."""


class PDFLaTeXMissingError(MissingExecutableError):
    """Kept as its own name: callers of ``table_rendering`` catch this one."""


def require_executable(command, error_class=MissingExecutableError):
    if shutil.which(command) is None:
        raise error_class(f"{command} should be installed!")
    return command


def have_executable(command):
    return shutil.which(command) is not None


@dataclass
class LogSummary:
    """What one LaTeX log says, parsed once."""

    text: str = ""
    errors: List[str] = field(default_factory=list)
    overfull_pt: List[float] = field(default_factory=list)
    undefined_references: List[str] = field(default_factory=list)
    undefined_citations: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    rerun_requested: bool = False
    undefined_summary: bool = False

    @property
    def worst_overfull_pt(self):
        return max(self.overfull_pt) if self.overfull_pt else 0.0

    @property
    def clean(self):
        return not (
            self.errors
            or self.undefined_references
            or self.undefined_citations
            or self.missing_files
            or self.undefined_summary
        )


def parse_log(text):
    """Parse a LaTeX log (or a driver's stdout when no log was written)."""
    return LogSummary(
        text=text,
        errors=[error.strip() for error in _LATEX_ERROR.findall(text)],
        overfull_pt=[float(amount) for amount in _OVERFULL_HBOX.findall(text)],
        undefined_references=sorted(set(_UNDEFINED_REFERENCE.findall(text))),
        undefined_citations=sorted(set(_UNDEFINED_CITATION.findall(text))),
        missing_files=sorted(set(_MISSING_FILE.findall(text))),
        rerun_requested=bool(_RERUN.search(text)),
        undefined_summary=bool(_UNDEFINED_SUMMARY.search(text)),
    )


def read_log(directory, stem, fallback=""):
    path = os.path.join(directory, stem + ".log")
    if os.path.isfile(path):
        with open(path, "r", errors="replace") as handle:
            return handle.read()
    return fallback


def build_status(pdf_mtime, newest_input_mtime, returncode, driver_name="latexmk"):
    """``(status, message)`` for one compile: ``"ok"`` | ``"warning"`` | ``"failed"``.

    The exit code alone cannot tell "fine" from "broken" (see the module docstring), so the
    PDF's freshness decides and the exit code only downgrades a success to a warning.
    """
    if pdf_mtime is None:
        return "failed", f"{driver_name} exited {returncode} and produced no PDF."
    if newest_input_mtime is not None and pdf_mtime < newest_input_mtime:
        return "failed", (
            f"{driver_name} exited {returncode} and left the PDF older than the sources; "
            "the previous one is still being shown."
        )
    if returncode == 0:
        return "ok", ""
    return "warning", (
        f"{driver_name} exited {returncode} but the PDF is up to date; "
        "check the log for unresolved references or BibTeX errors."
    )


@dataclass
class RunResult:
    returncode: int
    stdout: str
    log: LogSummary
    pdf_path: str = ""
    runs: int = 1

    @property
    def pdf_exists(self):
        return bool(self.pdf_path) and os.path.isfile(self.pdf_path)


def _run(command, cwd):
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, errors="replace")


def run_pdflatex(tex_name, cwd, runs=2, max_runs=MAX_PDFLATEX_RUNS, halt_on_error=False):
    """Compile with pdflatex alone -- no latexmk, no BibTeX -- and parse the final log.

    This is the isolation check a submitted source package has to pass: the journal's
    pipeline is not obliged to run anything else. Extra passes are taken while LaTeX asks for
    them, up to ``max_runs``, so settled cross-references are not mistaken for broken ones.
    """
    require_executable(PDFLATEX_COMMAND, PDFLaTeXMissingError)
    stem = os.path.splitext(tex_name)[0]
    command = [PDFLATEX_COMMAND, "-interaction=nonstopmode"]
    if halt_on_error:
        command.append("-halt-on-error")
    command.append(tex_name)

    performed = 0
    process = None
    summary = LogSummary()
    while performed < max_runs:
        process = _run(command, cwd)
        performed += 1
        summary = parse_log(read_log(cwd, stem, process.stdout))
        if performed >= runs and not summary.rerun_requested:
            break
        if summary.errors:
            break
    pdf_path = os.path.join(cwd, stem + ".pdf")
    return RunResult(
        returncode=process.returncode if process else 1,
        stdout=process.stdout if process else "",
        log=summary,
        pdf_path=pdf_path,
        runs=performed,
    )


def run_latexmk(tex_name, cwd, extra_arguments=()):
    """Full build with latexmk: BibTeX included, and re-run as often as it takes.

    RevTeX needs this. Citations inside ``\\footnote`` are written to a second bibliography
    database (``<stem>Notes.bib``) that only exists after the first BibTeX pass, so a single
    pass leaves them undefined.
    """
    require_executable(LATEXMK_COMMAND)
    stem = os.path.splitext(tex_name)[0]
    command = [LATEXMK_COMMAND, "-pdf", "-f", "-interaction=nonstopmode"]
    command += list(extra_arguments)
    command.append(tex_name)
    process = _run(command, cwd)
    summary = parse_log(read_log(cwd, stem, process.stdout))
    return RunResult(
        returncode=process.returncode,
        stdout=process.stdout + process.stderr,
        log=summary,
        pdf_path=os.path.join(cwd, stem + ".pdf"),
    )


def bibtex_warnings(directory, stem):
    """Warnings BibTeX wrote to ``<stem>.blg`` (an empty year, a missing field, ...)."""
    path = os.path.join(directory, stem + ".blg")
    if not os.path.isfile(path):
        return []
    with open(path, "r", errors="replace") as handle:
        text = handle.read()
    return [line.strip() for line in text.splitlines() if line.startswith("Warning--")]


def pdf_page_count(path):
    """Page count via ``pdfinfo``, or ``None`` when it is unavailable or fails."""
    if not have_executable("pdfinfo"):
        return None
    process = _run(["pdfinfo", os.path.abspath(path)], os.path.dirname(os.path.abspath(path)))
    if process.returncode != 0:
        return None
    for line in process.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def pdf_page_size_cm(path):
    """``(width_cm, height_cm)`` of a PDF's first page, or ``None``."""
    if not have_executable("pdfinfo"):
        return None
    process = _run(["pdfinfo", os.path.abspath(path)], os.path.dirname(os.path.abspath(path)))
    if process.returncode != 0:
        return None
    match = re.search(r"Page size:\s+([0-9.]+) x ([0-9.]+) pts", process.stdout)
    if match is None:
        return None
    points_per_cm = 72.0 / 2.54
    return (float(match.group(1)) / points_per_cm, float(match.group(2)) / points_per_cm)


def unembedded_fonts(path):
    """Fonts ``pdffonts`` reports as not embedded; ``None`` when pdffonts is missing."""
    if not have_executable(PDFFONTS_COMMAND):
        return None
    process = _run(
        [PDFFONTS_COMMAND, os.path.abspath(path)], os.path.dirname(os.path.abspath(path))
    )
    if process.returncode != 0:
        return []
    names = []
    for line in process.stdout.splitlines()[2:]:
        columns = line.split()
        if len(columns) < 5:
            continue
        # name type encoding emb sub uni ...
        if columns[3] == "no":
            names.append(columns[0])
    return names


def kpsewhich(name):
    """Absolute path of a TeX file known to the installation, or ``None``."""
    if not have_executable(KPSEWHICH_COMMAND):
        return None
    process = _run([KPSEWHICH_COMMAND, name], os.getcwd())
    found = process.stdout.strip()
    return found or None
