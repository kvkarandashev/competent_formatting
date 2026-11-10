"""What every source packager does, whoever the package is for.

A journal upload (``jcp_source.py``) and an arXiv upload (``arxiv_source.py``) want different
things in the end, but they get there by the same steps: flatten each document, strip its
revision markup, build it once with BibTeX for the ``.bbl``, copy and rename the figures,
splice the bibliography in, and then -- the step that makes the package worth anything --
compile the shipped files alone in an empty directory with ``pdflatex`` only. Those steps live
here, once, so a fix to any of them reaches both packagers.

Sources are never modified; everything happens in the output directory.
"""

import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import List

from .flatten import (
    FlattenError,
    assign_graphic_names,
    find_graphics,
    flatten,
    graphicspath_directories,
    remove_spans,
    resolve_graphic,
    rewrite_graphics,
)
from .jcp_checks import ERROR, INFO, WARNING, Check
from .latex_build import (
    bibtex_warnings,
    have_executable,
    kpsewhich,
    pdf_page_count,
    run_latexmk,
    run_pdflatex,
)
from .latex_spans import code_spans
from .macro_removal import IncompleteSpecialMacro, clean_markup
from .unicode_ascii import UnmappedCharacterError, to_ascii

SOURCE_DIRNAME = "source"
BUILD_DIRNAME = "build"
FULL_BUILD = "full"
VERIFY_BUILD = "verify"
REPORT_NAME = "report.md"
ZIP_NAME = "source.zip"

# Never copied into the build tree: compiler droppings, and the project's own latexmkrc,
# whose custom dependencies (an \externaldocument rule, say) would run sub-builds we do not
# want and the recipient would not have.
AUX_SUFFIXES = {
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".lof",
    ".lot",
    ".nav",
    ".out",
    ".run.xml",
    ".snm",
    ".synctex.gz",
    ".toc",
    ".vrb",
}
SKIP_NAMES = {"latexmkrc", ".latexmkrc"}
SKIP_DIRS = {".git", "__pycache__", ".ipynb_checkpoints", ".cf_view"}

OVERFULL_REPORT_THRESHOLD_PT = 10.0

_BIBLIOGRAPHY = re.compile(r"\\bibliography\s*\{([^}]*)\}")
_BIBLIOGRAPHYSTYLE = re.compile(r"\\bibliographystyle\s*\{([^}]*)\}")
_BIBLATEX = re.compile(r"\\(addbibresource|printbibliography)\b")


class SourcePackageError(Exception):
    """A condition that stops the pipeline: the package cannot be assembled at all."""


class SourcePackageUsageError(SourcePackageError):
    """Wrong arguments or a missing tool -- the user's input, not the manuscript's content.

    Kept apart so the CLI can exit 2 (usage) rather than 1 (a check failed): the difference
    matters to whoever is reading the exit code in a script.
    """


@dataclass(frozen=True)
class Markup:
    """The revision markup to strip; see :func:`.macro_removal.clean_markup`."""

    opened_macros: tuple = ()
    removed_macros: tuple = ()
    opened_envs: tuple = ()
    removed_envs: tuple = ()

    def clean(self, text):
        return clean_markup(
            text, self.opened_macros, self.removed_macros, self.opened_envs, self.removed_envs
        )


@dataclass(kw_only=True)
class SourcePackageResult:
    """Checks and artifacts shared by every packager; subclasses add their own outputs."""

    out_dir: str
    checks: List[Check] = field(default_factory=list)
    figure_map: list = field(default_factory=list)
    replacements: list = field(default_factory=list)
    bibtex_warnings: List[str] = field(default_factory=list)
    zip_path: str = None
    report_path: str = None

    @property
    def source_dir(self):
        return os.path.join(self.out_dir, SOURCE_DIRNAME)

    @property
    def hard_failures(self):
        return [check for check in self.checks if check.level == ERROR]

    @property
    def warnings(self):
        return [check for check in self.checks if check.level == WARNING]

    @property
    def passed(self):
        return not self.hard_failures

    def add(self, level, category, message):
        self.checks.append(Check(level, category, message))

    # What render_report puts above and below the shared sections.
    report_title = "Source package"

    def report_header(self):
        return [f"- output directory: `{self.out_dir}`"]

    def report_footer(self):
        return []


# ==================================================================================
# Output and build directories
# ==================================================================================


def _skip_path(relative):
    parts = relative.split(os.sep)
    if any(part in SKIP_DIRS for part in parts):
        return True
    if parts[-1] in SKIP_NAMES:
        return True
    return any(parts[-1].endswith(suffix) for suffix in AUX_SUFFIXES)


def copy_project(root, destination, skip_roots=()):
    """Copy the manuscript tree, minus compiler artifacts and the project's latexmkrc."""
    skip_roots = [os.path.realpath(path) for path in skip_roots]
    os.makedirs(destination, exist_ok=True)
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in SKIP_DIRS
            and os.path.realpath(os.path.join(directory, name)) not in skip_roots
        ]
        for name in names:
            source = os.path.join(directory, name)
            relative = os.path.relpath(source, root)
            if _skip_path(relative):
                continue
            target = os.path.join(destination, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)


def prepare_out_dir(out_dir, project_root, artifact_names, force=False):
    """Create (or clear) the output directory, refusing anything that could destroy work.

    ``--force`` only ever removes ``artifact_names`` and PDFs -- the names the packager
    writes -- so pointing ``--out`` at a directory holding anything else fails instead of
    deleting the user's work.
    """
    out_dir = os.path.abspath(out_dir)
    project_root = os.path.abspath(project_root)
    if out_dir == project_root:
        raise SourcePackageUsageError(
            f"--out {out_dir} is the manuscript directory itself; pick a separate directory"
        )
    if os.path.commonpath([out_dir, project_root]) == out_dir:
        raise SourcePackageUsageError(
            f"--out {out_dir} contains the manuscript directory; pick a separate directory"
        )
    if os.path.exists(out_dir):
        existing = sorted(os.listdir(out_dir))
        if existing and not force:
            raise SourcePackageUsageError(
                f"--out {out_dir} is not empty; pass --force to replace what is in it"
            )
        unknown = [
            name for name in existing if name not in artifact_names and not name.endswith(".pdf")
        ]
        if unknown:
            raise SourcePackageUsageError(
                f"--out {out_dir} holds files this tool did not write ({', '.join(unknown[:5])}"
                f"{', ...' if len(unknown) > 5 else ''}); delete it yourself if that is intended"
            )
        for name in existing:
            path = os.path.join(out_dir, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="strict") as handle:
        return handle.read()


def make_zip(source_dir, zip_path):
    """Archive ``source_dir``'s contents, paths relative to it (no enclosing folder)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory, subdirectories, names in os.walk(source_dir):
            subdirectories.sort()
            for name in sorted(names):
                path = os.path.join(directory, name)
                archive.write(path, arcname=os.path.relpath(path, source_dir))
    return zip_path


# ==================================================================================
# One document: flatten, clean, normalise
# ==================================================================================


def remap_origins(old_lines, new_lines, old_origins):
    """Carry per-line provenance across a rewrite that changed some lines.

    Macro removal shortens or deletes lines, so the line numbers of the cleaned text no
    longer index the flattened one. A line diff recovers the mapping exactly where lines
    survived untouched, which is everywhere the author will be asked to look.
    """
    from difflib import SequenceMatcher

    origins = [None] * len(new_lines)
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(j2 - j1):
                if i1 + offset < len(old_origins):
                    origins[j1 + offset] = old_origins[i1 + offset]
        else:
            fallback = old_origins[i1] if i1 < len(old_origins) else None
            for index in range(j1, j2):
                origins[index] = fallback
    return origins


def origin_lookup(origins):
    def lookup(line_number):
        index = line_number - 1
        if 0 <= index < len(origins):
            return origins[index]
        return None

    return lookup


def flatten_and_clean(tex_path, markup, keep_comments=False, root=None):
    """``(flat, cleaned, leftovers)``: the flattened document, and it with markup stripped.

    The text-only core shared by ``cf_flatten`` and the packagers; raises
    :class:`SourcePackageError` for anything that stops it.
    """
    try:
        flat = flatten(tex_path, root=root, keep_comments=keep_comments)
    except FlattenError as error:
        raise SourcePackageError(str(error)) from error
    try:
        cleaned, leftovers = markup.clean(flat.text)
    except IncompleteSpecialMacro as error:
        raise SourcePackageError(f"revision markup is unbalanced: {error}") from error
    return flat, cleaned, leftovers


def prepare_document(tex_path, root, markup, result, keep_comments=False, ascii=True, label=""):
    """Flatten, strip markup and (optionally) normalise to ASCII, recording what happened."""
    flat, cleaned, leftovers = flatten_and_clean(tex_path, markup, keep_comments, root=root)
    prefix = f"{label}: " if label else ""
    for inlined in dict.fromkeys(flat.inputs):
        result.add(INFO, "flatten", f"{prefix}inlined {inlined}")
    for leftover in leftovers:
        result.add(
            ERROR,
            "markup",
            f"{prefix}{leftover} still appears after cleaning; it is probably used in a way the "
            "stripper did not recognise (check for an unbalanced brace)",
        )
    if not ascii:
        return cleaned
    origins = remap_origins(flat.text.splitlines(), cleaned.splitlines(), flat.origins)
    try:
        cleaned, replacements = to_ascii(cleaned, origin_of_line=origin_lookup(origins))
    except UnmappedCharacterError as error:
        raise SourcePackageError(error.render()) from error
    result.replacements += replacements
    return cleaned


def full_build(tex_name, cwd, result, label=""):
    """latexmk with BibTeX, for the ``.bbl`` and a reference page count; ``(run, pages)``."""
    stem = os.path.splitext(tex_name)[0]
    built = run_latexmk(tex_name, cwd)
    warnings = bibtex_warnings(cwd, stem)
    result.bibtex_warnings += [f"{label}: {w}" for w in warnings] if label else warnings
    if not built.pdf_exists:
        result.add(
            ERROR,
            "build",
            f"{label or 'the cleaned manuscript'} did not compile in the full build; "
            f"{'; '.join(built.log.errors[:3]) or 'see ' + cwd}",
        )
        return built, None
    return built, pdf_page_count(built.pdf_path)


# ==================================================================================
# Bibliography
# ==================================================================================


def find_bibliography(text):
    """``(span, databases)`` of the single ``\\bibliography`` command, or ``(None, [])``."""
    matches = []
    for span in code_spans(text):
        for match in _BIBLIOGRAPHY.finditer(text, span.start, span.end):
            matches.append(match)
        if _BIBLATEX.search(text, span.start, span.end):
            raise SourcePackageError(
                "biblatex (\\addbibresource/\\printbibliography) is not supported: the package "
                "ships a BibTeX .bbl, which is what RevTeX/natbib pipelines expect"
            )
    if not matches:
        return None, []
    if len(matches) > 1:
        raise SourcePackageError(
            f"{len(matches)} \\bibliography commands found; a flat submission needs exactly one"
        )
    match = matches[0]
    return (match.start(), match.end()), [
        name.strip() for name in match.group(1).split(",") if name.strip()
    ]


def inline_bibliography(text, span, bbl_text):
    """Splice the ``.bbl`` in where ``\\bibliography`` was, literally.

    Literal is the whole point: a ``.bbl`` is dense with backslashes, and ``re.sub`` would
    read ``\\1`` or ``\\g<0>`` in a title as a replacement-group reference and corrupt the
    bibliography. Slicing cannot.
    """
    return text[: span[0]] + bbl_text.rstrip("\n") + text[span[1] :]


def drop_bibliographystyle(text):
    spans = []
    for span in code_spans(text):
        for match in _BIBLIOGRAPHYSTYLE.finditer(text, span.start, span.end):
            spans.append((match.start(), match.end()))
    return remove_spans(text, spans)


def ship_local_bst(text, root, source_dir, result):
    """A ``.bst`` living in the project travels with a separately shipped ``.bbl``.

    Only then: with the bibliography inlined, nothing re-runs BibTeX and the style file is
    dead weight.
    """
    for match in _BIBLIOGRAPHYSTYLE.finditer(text):
        name = match.group(1).strip()
        local = os.path.join(root, name + ".bst")
        if os.path.isfile(local):
            shutil.copy2(local, os.path.join(source_dir, name + ".bst"))
            result.add(INFO, "bibliography", f"shipped the project's own {name}.bst")


def splice_bibliography(
    text, bbl_path, mode, root, source_dir, result, ascii=True, missing_level=WARNING
):
    """Inline the ``.bbl`` (``mode="inline"``) or ship it beside the source (``"separate"``)."""
    stem = os.path.splitext(os.path.basename(bbl_path))[0]
    span, databases = find_bibliography(text)
    if span is None:
        result.add(missing_level, "bibliography", f"{stem}: no \\bibliography command found")
        return text
    if not os.path.isfile(bbl_path):
        result.add(
            ERROR,
            "bibliography",
            f"BibTeX produced no {stem}.bbl, so the bibliography cannot be shipped; the "
            f"databases referenced are {', '.join(databases) or '(none)'}",
        )
        return text
    if mode == "inline":
        bbl_text = read_text(bbl_path)
        if ascii:
            bbl_text, bbl_replacements = to_ascii(bbl_text)
            for replacement in bbl_replacements:
                replacement.source = f"{stem}.bbl (from {', '.join(databases)})"
            result.replacements += bbl_replacements
        text = drop_bibliographystyle(inline_bibliography(text, span, bbl_text))
        result.add(INFO, "bibliography", f"inlined {stem}.bbl; no .bib is shipped")
        return text
    shutil.copy2(bbl_path, os.path.join(source_dir, stem + ".bbl"))
    ship_local_bst(text, root, source_dir, result)
    result.add(
        INFO,
        "bibliography",
        f"shipped {stem}.bbl beside the source; \\bibliography is kept and no .bib is "
        "shipped (pdflatex reads the .bbl directly)",
    )
    return text


# ==================================================================================
# Figures and style files
# ==================================================================================


def collect_figures(text, root, source_dir, prefix, result, check_figure=None):
    """Copy every graphic into the flat source directory and rewrite the references.

    ``check_figure(path, name, use, result)`` is the recipient's own vetting of each file. A
    shipped name already taken by a *different* file (two documents with the same prefix) is
    refused rather than overwritten.
    """
    directories, graphicspath_spans = graphicspath_directories(text)
    uses = find_graphics(text)
    resolved = []
    for use in uses:
        path = resolve_graphic(use.path, root, directories)
        if path is None:
            raise SourcePackageError(
                f"\\includegraphics{{{use.path}}}: no such file under {root}"
                + (f" or in \\graphicspath {directories}" if directories else "")
            )
        resolved.append(path)

    names = assign_graphic_names(uses, resolved, prefix=prefix)
    already_shipped = {name: source for source, name in result.figure_map}
    copied = {}
    for index, use in enumerate(uses):
        source = resolved[index]
        name = names[index]
        if name in copied:
            continue
        relative = os.path.relpath(source, root)
        if name in already_shipped and already_shipped[name] != relative:
            raise SourcePackageError(
                f"{name} would be shipped for both {already_shipped[name]} and {relative}; "
                "give the documents different figure prefixes"
            )
        copied[name] = source
        shutil.copy2(source, os.path.join(source_dir, name))
        result.figure_map.append((relative, name))
        if check_figure is not None:
            check_figure(source, name, use, result)

    text = rewrite_graphics(text, uses, names)
    return remove_spans(text, graphicspath_spans)


def ship_local_styles(parsed, root, source_dir, result):
    """Ship the project's own ``.cls``/``.sty``; warn about ones TeX cannot find at all."""
    local = []
    for name, extension in [(parsed.name, ".cls")] + [
        (package, ".sty") for package in dict.fromkeys(parsed.packages)
    ]:
        if not name:
            continue
        local_path = os.path.join(root, name + extension)
        if os.path.isfile(local_path):
            shutil.copy2(local_path, os.path.join(source_dir, name + extension))
            local.append(name + extension)
            continue
        if kpsewhich(name + extension) is None and have_executable("kpsewhich"):
            result.add(
                WARNING,
                "packages",
                f"{name}{extension} is neither in the project nor in this TeX installation; "
                "the recipient's installation may not have it either",
            )
    for name in local:
        result.add(INFO, "packages", f"shipped the project's own {name}")


# ==================================================================================
# Verification
# ==================================================================================


def prepare_eps(directory, result):
    """pdflatex cannot read EPS directly; give it the converted file the recipient would make."""
    eps_files = [name for name in os.listdir(directory) if name.lower().endswith((".eps", ".ps"))]
    if not eps_files:
        return
    if not have_executable("epstopdf"):
        result.add(
            WARNING,
            "figures",
            "epstopdf is not installed, so the EPS figures could not be converted for the "
            "verification build; the package itself is unaffected",
        )
        return
    import subprocess

    for name in eps_files:
        stem = os.path.splitext(name)[0]
        subprocess.run(
            ["epstopdf", name, f"--outfile={stem}-eps-converted-to.pdf"],
            cwd=directory,
            capture_output=True,
        )


def report_verification(verified, result, label=""):
    """Turn the isolated pdflatex build's log into checks."""
    prefix = f"{label}: " if label else ""
    for error in verified.log.errors[:10]:
        result.add(ERROR, "verify", f"{prefix}pdflatex: {error}")
    for reference in verified.log.undefined_references:
        result.add(ERROR, "verify", f"{prefix}undefined reference: {reference}")
    for citation in verified.log.undefined_citations:
        result.add(ERROR, "verify", f"{prefix}undefined citation: {citation}")
    for missing in verified.log.missing_files:
        result.add(ERROR, "verify", f"{prefix}missing file: {missing}")
    if verified.log.undefined_summary and not (
        verified.log.undefined_references or verified.log.undefined_citations
    ):
        result.add(
            ERROR,
            "verify",
            f"{prefix}LaTeX reported undefined references or citations; see the log",
        )
    if not verified.pdf_exists:
        result.add(ERROR, "verify", f"{prefix}pdflatex produced no PDF from the shipped files")
    overfull = [
        amount for amount in verified.log.overfull_pt if amount > OVERFULL_REPORT_THRESHOLD_PT
    ]
    if overfull:
        result.add(
            WARNING,
            "verify",
            f"{prefix}{len(overfull)} overfull box(es) over {OVERFULL_REPORT_THRESHOLD_PT:.0f}pt, "
            f"worst {max(overfull):.0f}pt -- something runs past the text width",
        )
    if verified.log.rerun_requested:
        result.add(
            WARNING, "verify", f"{prefix}LaTeX still asked for another pass after the last run"
        )


def verify_in_isolation(source_dir, verify_dir, tex_names, result, label_each=False):
    """Compile the shipped files, alone, with pdflatex only -- the package's guarantee.

    ``source_dir`` is copied into the empty ``verify_dir`` and each of ``tex_names`` is
    compiled there in order, as the recipient would. Returns ``{tex_name: (run, pages)}``.
    """
    shutil.copytree(source_dir, verify_dir, dirs_exist_ok=True)
    prepare_eps(verify_dir, result)
    outcomes = {}
    for tex_name in tex_names:
        verified = run_pdflatex(tex_name, verify_dir, runs=2)
        report_verification(verified, result, label=tex_name if label_each else "")
        pages = pdf_page_count(verified.pdf_path) if verified.pdf_exists else None
        outcomes[tex_name] = (verified, pages)
    return outcomes


def compare_page_counts(built_pages, verified_pages, result, label=""):
    if built_pages and verified_pages and built_pages != verified_pages:
        result.add(
            WARNING,
            "verify",
            f"{label + ': ' if label else ''}the flat package compiles to {verified_pages} "
            f"pages but the full build gave {built_pages}; something changed during flattening",
        )


# ==================================================================================
# Report
# ==================================================================================


def render_report(result):
    """The ``report.md``: the packager's header, then checks, figures, replacements."""
    lines = [f"# {result.report_title}", ""]
    lines += result.report_header()
    lines.append("")

    errors = [check for check in result.checks if check.level == ERROR]
    warnings = [check for check in result.checks if check.level == WARNING]
    infos = [check for check in result.checks if check.level == INFO]

    lines.append(
        f"**{'FAILED' if errors else 'PASSED'}** "
        f"-- {len(errors)} hard failure(s), {len(warnings)} warning(s)."
    )
    lines.append("")

    for title, group in (
        ("Hard failures", errors),
        ("Warnings", warnings),
        ("Notes", infos),
    ):
        if not group:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for check in group:
            lines.append(f"- **{check.category}**: {check.message}")
        lines.append("")

    if result.figure_map:
        lines += ["## Figures", "", "| source | shipped as |", "|---|---|"]
        for original, new in result.figure_map:
            lines.append(f"| `{original}` | `{new}` |")
        lines.append("")

    if result.replacements:
        lines += ["## Non-ASCII characters replaced", ""]
        grouped = {}
        for replacement in result.replacements:
            grouped.setdefault(replacement.source or "(flat document)", []).append(replacement)
        for source in sorted(grouped):
            lines.append(f"- `{source}`")
            for replacement in grouped[source]:
                lines.append(
                    f"  - U+{ord(replacement.character):04X} `{replacement.character}` -> "
                    f"`{replacement.replacement}`"
                )
        lines += [
            "",
            "These were fixed in the shipped copy only. The originals still hold them, so the",
            "same replacements will be needed again unless the `.tex`/`.bib` are corrected.",
            "",
        ]

    lines += result.report_footer()

    if result.bibtex_warnings:
        lines += ["## BibTeX warnings", ""]
        lines += [f"- {warning}" for warning in result.bibtex_warnings]
        lines.append("")

    return "\n".join(lines) + "\n"
