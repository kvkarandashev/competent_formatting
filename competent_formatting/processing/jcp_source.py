"""Turn a working manuscript into a source package J. Chem. Phys. will accept.

AIP asks for a flat set of files that compiles on its own: one ``.tex``, figures beside it,
no subdirectories, and an author-generated PDF built from exactly those files. A working
manuscript is none of those things, and the gap is where submissions break -- a forgotten
``\\input``, a figure path that only resolves on the author's machine, a bibliography that
needs the ``.bib`` and two BibTeX passes, revision markup still coloured red.

So the package is not assembled and hoped for: it is **verified**. The last step copies the
shipped files into an empty directory and compiles them there with ``pdflatex`` alone -- no
``latexmk``, no BibTeX, no ``latexmkrc``, nothing from the project. If a reference is
undefined or a file is missing there, it would be missing at the journal too, and that is a
hard failure rather than a line in a log nobody reads.

Sources are never modified; everything happens in the output directory.

What is *not* verifiable from AIP's public pages is whether their TeX pipeline runs BibTeX or
accepts subdirectories. The defaults here are the ones that are correct either way: flat
directory, bibliography inlined from the ``.bbl``, no ``.bib`` shipped.
"""

import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
from .jcp_checks import (
    ERROR,
    INFO,
    MAX_FIGURE_HEIGHT_CM,
    MAX_FIGURE_WIDTH_CM,
    MIN_RASTER_DPI,
    WARNING,
    Check,
    alt_text_draft,
    captions,
    check_class,
    check_duplicate_packages,
    check_float_citation_order,
    lint_prose,
    parse_class_and_packages,
    render_report,
)
from .latex_build import (
    bibtex_warnings,
    have_executable,
    kpsewhich,
    pdf_page_count,
    pdf_page_size_cm,
    require_executable,
    run_latexmk,
    run_pdflatex,
    unembedded_fonts,
)
from .latex_spans import code_spans
from .macro_removal import IncompleteSpecialMacro, remove_macros
from .unicode_ascii import UnmappedCharacterError, to_ascii

SOURCE_DIRNAME = "source"
BUILD_DIRNAME = "build"
FULL_BUILD = "full"
VERIFY_BUILD = "verify"
MARKED_BUILD = "marked"
ALT_TEXT_NAME = "alt_text.txt"
REPORT_NAME = "report.md"
ZIP_NAME = "source.zip"

# Top-level names this tool writes. --force only ever removes these, so pointing --out at a
# directory that holds something else fails instead of deleting the user's work.
ARTIFACT_NAMES = {SOURCE_DIRNAME, BUILD_DIRNAME, ALT_TEXT_NAME, REPORT_NAME, ZIP_NAME}

# Never copied into the build tree: compiler droppings, and the project's own latexmkrc,
# whose custom dependencies (an \externaldocument rule, say) would run sub-builds we do not
# want and the journal would not have.
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


class JCPSourceError(Exception):
    """A condition that stops the pipeline: the package cannot be assembled at all."""


class JCPUsageError(JCPSourceError):
    """Wrong arguments or a missing tool -- the user's input, not the manuscript's content.

    Kept apart so the CLI can exit 2 (usage) rather than 1 (a check failed): the difference
    matters to whoever is reading the exit code in a script.
    """


@dataclass
class JCPSourceResult:
    out_dir: str
    main_name: str
    checks: List[Check] = field(default_factory=list)
    figure_map: List[Tuple[str, str]] = field(default_factory=list)
    replacements: list = field(default_factory=list)
    bibtex_warnings: List[str] = field(default_factory=list)
    pdf_path: Optional[str] = None
    sm_pdf_path: Optional[str] = None
    marked_pdf_path: Optional[str] = None
    zip_path: Optional[str] = None
    alt_text_path: Optional[str] = None
    report_path: Optional[str] = None
    page_counts: Optional[Tuple[Optional[int], Optional[int]]] = None

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


def prepare_out_dir(out_dir, project_root, force=False):
    """Create (or clear) the output directory, refusing anything that could destroy work."""
    out_dir = os.path.abspath(out_dir)
    project_root = os.path.abspath(project_root)
    if out_dir == project_root:
        raise JCPUsageError(
            f"--out {out_dir} is the manuscript directory itself; pick a separate directory"
        )
    if os.path.commonpath([out_dir, project_root]) == out_dir:
        raise JCPUsageError(
            f"--out {out_dir} contains the manuscript directory; pick a separate directory"
        )
    if os.path.exists(out_dir):
        existing = sorted(os.listdir(out_dir))
        if existing and not force:
            raise JCPUsageError(
                f"--out {out_dir} is not empty; pass --force to replace what is in it"
            )
        unknown = [
            name for name in existing if name not in ARTIFACT_NAMES and not name.endswith(".pdf")
        ]
        if unknown:
            raise JCPUsageError(
                f"--out {out_dir} holds files this tool did not write ({', '.join(unknown[:5])}"
                f"{', ...' if len(unknown) > 5 else ''}); delete it yourself if that is intended"
            )
        for name in existing:
            path = os.path.join(out_dir, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def clean_markup(text, opened_macros, removed_macros, opened_envs, removed_envs):
    """Strip revision markup, then prove none of it is left."""
    if not any([opened_macros, removed_macros, opened_envs, removed_envs]):
        return text, []
    try:
        cleaned = remove_macros(
            text,
            opened_fields=list(opened_macros),
            removed_fields=list(removed_macros),
            opened_envs=list(opened_envs),
            removed_envs=list(removed_envs),
        )
    except IncompleteSpecialMacro as error:
        raise JCPSourceError(f"revision markup is unbalanced: {error}") from error

    leftovers = []
    names = set(opened_macros) | set(removed_macros)
    environments = set(opened_envs) | set(removed_envs)
    for span in code_spans(cleaned):
        chunk = cleaned[span.start : span.end]
        for name in sorted(names):
            if re.search(r"\\" + re.escape(name) + r"(?![a-zA-Z@])", chunk):
                leftovers.append(f"\\{name}")
        for name in sorted(environments):
            if re.search(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}", chunk):
                leftovers.append(f"{name} environment")
    return cleaned, sorted(set(leftovers))


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


def _origin_lookup(origins):
    def lookup(line_number):
        index = line_number - 1
        if 0 <= index < len(origins):
            return origins[index]
        return None

    return lookup


def find_bibliography(text):
    """``(span, databases)`` of the single ``\\bibliography`` command, or ``(None, [])``."""
    matches = []
    for span in code_spans(text):
        for match in _BIBLIOGRAPHY.finditer(text, span.start, span.end):
            matches.append(match)
        if _BIBLATEX.search(text, span.start, span.end):
            raise JCPSourceError(
                "biblatex (\\addbibresource/\\printbibliography) is not supported: AIP's "
                "pipeline expects BibTeX via RevTeX/natbib"
            )
    if not matches:
        return None, []
    if len(matches) > 1:
        raise JCPSourceError(
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


def _ship_local_bst(text, root, source_dir, result):
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


def collect_figures(text, root, source_dir, prefix, result):
    """Copy every graphic into the flat source directory and rewrite the references."""
    directories, graphicspath_spans = graphicspath_directories(text)
    uses = find_graphics(text)
    resolved = []
    for use in uses:
        path = resolve_graphic(use.path, root, directories)
        if path is None:
            raise JCPSourceError(
                f"\\includegraphics{{{use.path}}}: no such file under {root}"
                + (f" or in \\graphicspath {directories}" if directories else "")
            )
        resolved.append(path)

    names = assign_graphic_names(uses, resolved, prefix=prefix)
    copied = {}
    for index, use in enumerate(uses):
        source = resolved[index]
        name = names[index]
        if name in copied:
            continue
        copied[name] = source
        shutil.copy2(source, os.path.join(source_dir, name))
        result.figure_map.append((os.path.relpath(source, root), name))
        _check_figure(source, name, use, result)

    text = rewrite_graphics(text, uses, names)
    return remove_spans(text, graphicspath_spans)


def _check_figure(path, name, use, result):
    extension = os.path.splitext(path)[1].lower()
    if extension == ".pdf":
        result.add(
            INFO,
            "figures",
            f"{name} is a PDF; for accepted manuscripts AIP prefers EPS, PS or TIFF and asks "
            "for PDF only when those cannot be generated",
        )
        missing = unembedded_fonts(path)
        if missing is None:
            result.add(WARNING, "figures", f"{name}: pdffonts is not installed, fonts not checked")
        elif missing:
            result.add(
                ERROR,
                "figures",
                f"{name} has fonts that are not embedded ({', '.join(missing)}); AIP requires "
                "every font to be embedded",
            )
        size = pdf_page_size_cm(path)
        if size is not None:
            width, height = size
            if width > MAX_FIGURE_WIDTH_CM or height > MAX_FIGURE_HEIGHT_CM:
                result.add(
                    WARNING,
                    "figures",
                    f"{name} measures {width:.1f} x {height:.1f} cm, over AIP's "
                    f"{MAX_FIGURE_WIDTH_CM} x {MAX_FIGURE_HEIGHT_CM} cm limit (it is scaled by "
                    "\\includegraphics, so this is only about the file itself)",
                )
    elif extension in (".eps", ".ps"):
        result.add(
            INFO,
            "figures",
            f"{name} is {extension}, which AIP prefers -- but pdflatex cannot read it without "
            "epstopdf, so the isolated verification build converts it first",
        )
    elif extension in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        _check_raster(path, name, use, result)


def _printed_width_cm(options):
    """How wide the figure will be printed, from ``width=0.4\\textwidth`` and friends.

    Only the fraction-of-a-length form can be resolved without compiling, and the lengths are
    taken as AIP's page geometry (a column is 8.5 cm, the text block 17 cm). That is an
    assumption, so what it feeds is a warning and never a failure.
    """
    match = re.search(r"width\s*=\s*([0-9.]*)\s*\\(textwidth|columnwidth|linewidth)", options)
    if match is None:
        return None
    fraction = float(match.group(1)) if match.group(1) else 1.0
    basis = MAX_FIGURE_WIDTH_CM if match.group(2) == "textwidth" else MAX_FIGURE_WIDTH_CM / 2
    return fraction * basis


def _check_raster(path, name, use, result):
    try:
        from PIL import Image  # noqa: PLC0415  (optional, and deliberately not a dependency)
    except ImportError:
        return
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        return
    printed_cm = _printed_width_cm(use.options)
    if printed_cm is None or printed_cm <= 0:
        result.add(INFO, "figures", f"{name} is {width}x{height} px")
        return
    dpi = width / (printed_cm / 2.54)
    level = WARNING if dpi < MIN_RASTER_DPI else INFO
    result.add(
        level,
        "figures",
        f"{name} is {width}x{height} px, about {dpi:.0f} dpi at the {printed_cm:.1f} cm it is "
        f"printed at (AIP asks for at least {MIN_RASTER_DPI} dpi for colour)",
    )


def _verify_ascii(text, path, result):
    offenders = [character for character in text if ord(character) > 127]
    if offenders:
        unique = sorted(set(offenders))
        result.add(
            ERROR,
            "unicode",
            f"{os.path.basename(path)} still holds non-ASCII characters "
            f"({', '.join('U+%04X' % ord(character) for character in unique[:8])}); they sit "
            "inside a verbatim or \\url context, which cannot be rewritten automatically -- "
            "fix them in the original source",
        )


def _check_flat_layout(source_dir, result):
    for entry in sorted(os.listdir(source_dir)):
        if os.path.isdir(os.path.join(source_dir, entry)):
            result.add(
                ERROR,
                "layout",
                f"{entry}/ is a subdirectory of the source package; AIP's upload is flat",
            )


def check_packages(parsed, root, source_dir, result):
    """Ship local style files, and warn about packages the journal may not have."""
    result.checks += check_class(parsed)
    result.checks += check_duplicate_packages(parsed)
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
                "the journal's installation may not have it either",
            )
    for name in local:
        result.add(INFO, "packages", f"shipped the project's own {name}")


def _write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read(path):
    with open(path, "r", encoding="utf-8", errors="strict") as handle:
        return handle.read()


def make_zip(source_dir, zip_path):
    """A flat archive: the files, with no directory component inside the zip."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(os.listdir(source_dir)):
            path = os.path.join(source_dir, name)
            if os.path.isfile(path):
                archive.write(path, arcname=name)
    return zip_path


def build_jcp_source(
    main_tex,
    out_dir,
    si=None,
    opened_macros=(),
    removed_macros=(),
    opened_envs=(),
    removed_envs=(),
    bbl="inline",
    keep_comments=False,
    figure_prefix="fig",
    engine="pdflatex",
    marked_pdf=False,
    make_archive=True,
    force=False,
    log=lambda message: None,
):
    """Assemble, verify and report one submission package. See the module docstring."""
    if engine != "pdflatex":
        raise JCPUsageError(
            f"engine {engine!r} is not supported yet; AIP's pipeline is pdflatex and that is "
            "the only one this tool can verify against"
        )
    require_executable("pdflatex")
    require_executable("latexmk")

    main_tex = os.path.abspath(main_tex)
    if not os.path.isfile(main_tex):
        raise JCPUsageError(f"no such file: {main_tex}")
    root = os.path.dirname(main_tex)
    main_name = os.path.basename(main_tex)
    stem = os.path.splitext(main_name)[0]

    out_dir = prepare_out_dir(out_dir, root, force=force)
    source_dir = os.path.join(out_dir, SOURCE_DIRNAME)
    os.makedirs(source_dir, exist_ok=True)
    build_root = os.path.join(out_dir, BUILD_DIRNAME)
    result = JCPSourceResult(out_dir=out_dir, main_name=main_name)

    # 1. flatten -------------------------------------------------------------------
    log("flattening " + main_name)
    try:
        flat = flatten(main_tex, root=root, keep_comments=keep_comments)
    except FlattenError as error:
        raise JCPSourceError(str(error)) from error
    for inlined in dict.fromkeys(flat.inputs):
        result.add(INFO, "flatten", f"inlined {inlined}")

    # 2. revision markup -----------------------------------------------------------
    cleaned, leftovers = clean_markup(
        flat.text, opened_macros, removed_macros, opened_envs, removed_envs
    )
    for leftover in leftovers:
        result.add(
            ERROR,
            "markup",
            f"{leftover} still appears after cleaning; it is probably used in a way the "
            "stripper did not recognise (check for an unbalanced brace)",
        )
    origins = remap_origins(flat.text.splitlines(), cleaned.splitlines(), flat.origins)

    # 3. non-ASCII, with the provenance the author needs ---------------------------
    try:
        cleaned, replacements = to_ascii(cleaned, origin_of_line=_origin_lookup(origins))
    except UnmappedCharacterError as error:
        raise JCPSourceError(error.render()) from error
    result.replacements += replacements

    # 4. full build, for the .bbl and the reference page count ----------------------
    full_build = os.path.join(build_root, FULL_BUILD)
    log("building with latexmk (BibTeX) in " + os.path.relpath(full_build, out_dir))
    copy_project(root, full_build, skip_roots=[out_dir])
    _write(os.path.join(full_build, main_name), cleaned)
    full = run_latexmk(main_name, full_build)
    result.bibtex_warnings = bibtex_warnings(full_build, stem)
    built_pages = pdf_page_count(full.pdf_path) if full.pdf_exists else None
    if not full.pdf_exists:
        result.add(
            ERROR,
            "build",
            "the cleaned manuscript did not compile in the full build; "
            f"{'; '.join(full.log.errors[:3]) or 'see ' + full_build}",
        )

    # 5. figures -------------------------------------------------------------------
    log("collecting figures")
    cleaned = collect_figures(cleaned, root, source_dir, figure_prefix, result)

    # 6. bibliography --------------------------------------------------------------
    span, databases = find_bibliography(cleaned)
    bbl_path = os.path.join(full_build, stem + ".bbl")
    if span is not None:
        if not os.path.isfile(bbl_path):
            result.add(
                ERROR,
                "bibliography",
                f"BibTeX produced no {stem}.bbl, so the bibliography cannot be shipped; the "
                f"databases referenced are {', '.join(databases) or '(none)'}",
            )
        elif bbl == "inline":
            bbl_text = _read(bbl_path)
            bbl_text, bbl_replacements = to_ascii(bbl_text)
            for replacement in bbl_replacements:
                replacement.source = f"{stem}.bbl (from {', '.join(databases)})"
            result.replacements += bbl_replacements
            cleaned = inline_bibliography(cleaned, span, bbl_text)
            cleaned = drop_bibliographystyle(cleaned)
            result.add(INFO, "bibliography", f"inlined {stem}.bbl; no .bib is shipped")
        else:
            shutil.copy2(bbl_path, os.path.join(source_dir, stem + ".bbl"))
            _ship_local_bst(cleaned, root, source_dir, result)
            result.add(
                INFO,
                "bibliography",
                f"shipped {stem}.bbl beside the source; \\bibliography is kept and no .bib is "
                "shipped (pdflatex reads the .bbl directly)",
            )
    else:
        result.add(WARNING, "bibliography", "no \\bibliography command found")

    # 7. class, packages, local style files ----------------------------------------
    parsed = parse_class_and_packages(cleaned)
    check_packages(parsed, root, source_dir, result)

    # 8. write the flat source -----------------------------------------------------
    flat_path = os.path.join(source_dir, main_name)
    _write(flat_path, cleaned)
    _verify_ascii(cleaned, flat_path, result)
    _check_flat_layout(source_dir, result)

    # 9. lint ----------------------------------------------------------------------
    result.checks += lint_prose(cleaned)
    result.checks += check_float_citation_order(cleaned)

    # 10. the guarantee: compile the shipped files, alone, with pdflatex only -------
    log("verifying the package in an empty directory (pdflatex only)")
    verify_dir = os.path.join(build_root, VERIFY_BUILD)
    os.makedirs(verify_dir, exist_ok=True)
    for name in sorted(os.listdir(source_dir)):
        shutil.copy2(os.path.join(source_dir, name), os.path.join(verify_dir, name))
    _prepare_eps(verify_dir, result)
    verified = run_pdflatex(main_name, verify_dir, runs=2)
    _report_verification(verified, result)
    verified_pages = pdf_page_count(verified.pdf_path) if verified.pdf_exists else None
    result.page_counts = (built_pages, verified_pages)
    if built_pages and verified_pages and built_pages != verified_pages:
        result.add(
            WARNING,
            "verify",
            f"the flat package compiles to {verified_pages} pages but the full build gave "
            f"{built_pages}; something changed during flattening",
        )
    if verified.pdf_exists:
        result.pdf_path = os.path.join(out_dir, stem + ".pdf")
        shutil.copy2(verified.pdf_path, result.pdf_path)

    # 11. supplementary material ---------------------------------------------------
    main_captions = captions(cleaned)
    si_captions = []
    if si is not None:
        si_captions = _build_supplementary(
            si,
            root,
            full_build,
            out_dir,
            result,
            log,
            (opened_macros, removed_macros, opened_envs, removed_envs),
        )

    # 12. alt text, archive, report ------------------------------------------------
    result.alt_text_path = os.path.join(out_dir, ALT_TEXT_NAME)
    _write(result.alt_text_path, alt_text_draft(main_captions, si_captions))

    if marked_pdf:
        result.marked_pdf_path = _build_marked(
            root, build_root, out_dir, main_name, stem, result, log
        )

    if make_archive:
        result.zip_path = make_zip(source_dir, os.path.join(out_dir, ZIP_NAME))

    result.report_path = os.path.join(out_dir, REPORT_NAME)
    _write(result.report_path, render_report(result))
    return result


def _report_verification(verified, result):
    for error in verified.log.errors[:10]:
        result.add(ERROR, "verify", f"pdflatex: {error}")
    for reference in verified.log.undefined_references:
        result.add(ERROR, "verify", f"undefined reference: {reference}")
    for citation in verified.log.undefined_citations:
        result.add(ERROR, "verify", f"undefined citation: {citation}")
    for missing in verified.log.missing_files:
        result.add(ERROR, "verify", f"missing file: {missing}")
    if verified.log.undefined_summary and not (
        verified.log.undefined_references or verified.log.undefined_citations
    ):
        result.add(
            ERROR, "verify", "LaTeX reported undefined references or citations; see the log"
        )
    if not verified.pdf_exists:
        result.add(ERROR, "verify", "pdflatex produced no PDF from the shipped files")
    overfull = [
        amount for amount in verified.log.overfull_pt if amount > OVERFULL_REPORT_THRESHOLD_PT
    ]
    if overfull:
        result.add(
            WARNING,
            "verify",
            f"{len(overfull)} overfull box(es) over {OVERFULL_REPORT_THRESHOLD_PT:.0f}pt, worst "
            f"{max(overfull):.0f}pt -- something runs past the text width",
        )
    if verified.log.rerun_requested:
        result.add(WARNING, "verify", "LaTeX still asked for another pass after the last run")


def _prepare_eps(directory, result):
    """pdflatex cannot read EPS directly; give it the converted file the journal would make."""
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


def _build_supplementary(si, root, full_build, out_dir, result, log, markup):
    """Build the SM in the main document's build directory, so \\externaldocument resolves."""
    si_path = os.path.abspath(si)
    if not os.path.isfile(si_path):
        raise JCPUsageError(f"--si: no such file: {si_path}")
    si_name = os.path.basename(si_path)
    si_stem = os.path.splitext(si_name)[0]
    log(f"building supplementary material ({si_name})")

    opened_macros, removed_macros, opened_envs, removed_envs = markup
    si_text = _read(si_path)
    si_cleaned, leftovers = clean_markup(
        si_text, opened_macros, removed_macros, opened_envs, removed_envs
    )
    for leftover in leftovers:
        result.add(ERROR, "sm", f"{leftover} still appears in the supplementary material")
    _write(os.path.join(full_build, si_name), si_cleaned)

    built = run_latexmk(si_name, full_build)
    for reference in built.log.undefined_references:
        result.add(
            ERROR,
            "sm",
            f"undefined reference {reference!r} in the supplementary material"
            + (
                " (an M- reference needs the main document's .aux)"
                if reference.startswith("M-")
                else ""
            ),
        )
    for citation in built.log.undefined_citations:
        result.add(ERROR, "sm", f"undefined citation {citation!r} in the supplementary material")
    for error in built.log.errors[:5]:
        result.add(ERROR, "sm", f"pdflatex: {error}")
    if not built.pdf_exists:
        result.add(ERROR, "sm", "the supplementary material produced no PDF")
        return []
    result.sm_pdf_path = os.path.join(out_dir, si_stem + ".pdf")
    shutil.copy2(built.pdf_path, result.sm_pdf_path)
    result.add(
        INFO,
        "sm",
        "JCP takes supplementary material as a PDF only, so no SM source is packaged",
    )
    return captions(si_cleaned)


def _build_marked(root, build_root, out_dir, main_name, stem, result, log):
    """The manuscript *with* its revision markup, for the 'changes highlighted' upload."""
    log("building the marked copy")
    marked_dir = os.path.join(build_root, MARKED_BUILD)
    copy_project(root, marked_dir, skip_roots=[out_dir])
    built = run_latexmk(main_name, marked_dir)
    if not built.pdf_exists:
        result.add(WARNING, "marked", "the marked copy did not produce a PDF")
        return None
    target = os.path.join(out_dir, stem + "_marked.pdf")
    shutil.copy2(built.pdf_path, target)
    return target
