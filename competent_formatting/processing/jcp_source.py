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
from dataclasses import dataclass
from typing import Optional, Tuple

from . import source_package
from .external_labels import find_external_documents
from .jcp_checks import (
    ERROR,
    INFO,
    MAX_FIGURE_HEIGHT_CM,
    MAX_FIGURE_WIDTH_CM,
    MIN_RASTER_DPI,
    WARNING,
    alt_text_draft,
    captions,
    check_class,
    check_duplicate_packages,
    check_float_citation_order,
    lint_prose,
    parse_class_and_packages,
)
from .latex_build import pdf_page_size_cm, require_executable, run_latexmk, unembedded_fonts
from .source_package import (  # noqa: F401  (re-exported: the JCP API predates the split)
    BUILD_DIRNAME,
    FULL_BUILD,
    REPORT_NAME,
    SOURCE_DIRNAME,
    VERIFY_BUILD,
    ZIP_NAME,
    Markup,
    SourcePackageError,
    SourcePackageResult,
    SourcePackageUsageError,
    collect_figures,
    compare_page_counts,
    copy_project,
    drop_bibliographystyle,
    find_bibliography,
    full_build,
    inline_bibliography,
    make_zip,
    prepare_document,
    read_text,
    render_report,
    ship_local_styles,
    splice_bibliography,
    verify_in_isolation,
    write_text,
)

MARKED_BUILD = "marked"
ALT_TEXT_NAME = "alt_text.txt"

# Top-level names this tool writes. --force only ever removes these.
ARTIFACT_NAMES = {SOURCE_DIRNAME, BUILD_DIRNAME, ALT_TEXT_NAME, REPORT_NAME, ZIP_NAME}

# The packaging machinery is shared with cf_arxiv_source (source_package.py); these names are
# what the JCP side has always raised.
JCPSourceError = SourcePackageError
JCPUsageError = SourcePackageUsageError


@dataclass(kw_only=True)
class JCPSourceResult(SourcePackageResult):
    main_name: str
    pdf_path: Optional[str] = None
    sm_pdf_path: Optional[str] = None
    marked_pdf_path: Optional[str] = None
    sm_marked_pdf_path: Optional[str] = None
    alt_text_path: Optional[str] = None
    page_counts: Optional[Tuple[Optional[int], Optional[int]]] = None

    @property
    def report_title(self):
        return f"JCP source package: {os.path.basename(self.main_name)}"

    def report_header(self):
        lines = [f"- output directory: `{self.out_dir}`"]
        lines.append(f"- flat source: `{os.path.join('source', self.main_name)}`")
        if self.pdf_path:
            lines.append(f"- author PDF: `{os.path.basename(self.pdf_path)}`")
        if self.sm_pdf_path:
            lines.append(f"- supplementary PDF: `{os.path.basename(self.sm_pdf_path)}`")
        if self.marked_pdf_path:
            lines.append(f"- marked PDF: `{os.path.basename(self.marked_pdf_path)}`")
        if self.sm_marked_pdf_path:
            lines.append(
                f"- marked supplementary PDF: `{os.path.basename(self.sm_marked_pdf_path)}`"
            )
        if self.zip_path:
            lines.append(f"- upload archive: `{os.path.basename(self.zip_path)}`")
        return lines

    def report_footer(self):
        if not self.page_counts:
            return []
        built, verified = self.page_counts
        return [
            "## Page counts",
            "",
            f"- full build (BibTeX): {built}",
            f"- verified flat build (pdflatex only): {verified}",
            "",
        ]


def prepare_out_dir(out_dir, project_root, force=False):
    """Create (or clear) the output directory; see :func:`.source_package.prepare_out_dir`."""
    return source_package.prepare_out_dir(out_dir, project_root, ARTIFACT_NAMES, force=force)


def check_packages(parsed, root, source_dir, result):
    """Ship local style files, and warn about packages the journal may not have."""
    result.checks += check_class(parsed)
    result.checks += check_duplicate_packages(parsed)
    ship_local_styles(parsed, root, source_dir, result)


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
    markup = Markup(
        tuple(opened_macros), tuple(removed_macros), tuple(opened_envs), tuple(removed_envs)
    )

    out_dir = prepare_out_dir(out_dir, root, force=force)
    source_dir = os.path.join(out_dir, SOURCE_DIRNAME)
    os.makedirs(source_dir, exist_ok=True)
    build_root = os.path.join(out_dir, BUILD_DIRNAME)
    result = JCPSourceResult(out_dir=out_dir, main_name=main_name)

    # 1-3. flatten, strip revision markup, non-ASCII with provenance ---------------
    log("flattening " + main_name)
    cleaned = prepare_document(main_tex, root, markup, result, keep_comments=keep_comments)
    if find_external_documents(cleaned):
        raise JCPSourceError(
            "\\externaldocument -- the main file cannot reference another document"
        )

    # 4. full build, for the .bbl and the reference page count ----------------------
    full_dir = os.path.join(build_root, FULL_BUILD)
    log("building with latexmk (BibTeX) in " + os.path.relpath(full_dir, out_dir))
    copy_project(root, full_dir, skip_roots=[out_dir])
    write_text(os.path.join(full_dir, main_name), cleaned)
    _, built_pages = full_build(main_name, full_dir, result)

    # 5. figures -------------------------------------------------------------------
    log("collecting figures")
    cleaned = collect_figures(
        cleaned, root, source_dir, figure_prefix, result, check_figure=_check_figure
    )

    # 6. bibliography --------------------------------------------------------------
    cleaned = splice_bibliography(
        cleaned, os.path.join(full_dir, stem + ".bbl"), bbl, root, source_dir, result
    )

    # 7. class, packages, local style files ----------------------------------------
    check_packages(parse_class_and_packages(cleaned), root, source_dir, result)

    # 8. write the flat source -----------------------------------------------------
    flat_path = os.path.join(source_dir, main_name)
    write_text(flat_path, cleaned)
    _verify_ascii(cleaned, flat_path, result)
    _check_flat_layout(source_dir, result)

    # 9. lint ----------------------------------------------------------------------
    result.checks += lint_prose(cleaned)
    result.checks += check_float_citation_order(cleaned)

    # 10. the guarantee: compile the shipped files, alone, with pdflatex only -------
    log("verifying the package in an empty directory (pdflatex only)")
    verified, verified_pages = verify_in_isolation(
        source_dir, os.path.join(build_root, VERIFY_BUILD), [main_name], result
    )[main_name]
    result.page_counts = (built_pages, verified_pages)
    compare_page_counts(built_pages, verified_pages, result)
    if verified.pdf_exists:
        result.pdf_path = os.path.join(out_dir, stem + ".pdf")
        shutil.copy2(verified.pdf_path, result.pdf_path)

    # 11. supplementary material ---------------------------------------------------
    main_captions = captions(cleaned)
    si_captions = []
    if si is not None:
        si_captions = _build_supplementary(si, root, full_dir, out_dir, result, log, markup)

    # 12. alt text, archive, report ------------------------------------------------
    result.alt_text_path = os.path.join(out_dir, ALT_TEXT_NAME)
    write_text(result.alt_text_path, alt_text_draft(main_captions, si_captions))

    if marked_pdf:
        result.marked_pdf_path, result.sm_marked_pdf_path = _build_marked(
            root, build_root, out_dir, main_name, stem, result, log, si=si
        )

    if make_archive:
        result.zip_path = make_zip(source_dir, os.path.join(out_dir, ZIP_NAME))

    result.report_path = os.path.join(out_dir, REPORT_NAME)
    write_text(result.report_path, render_report(result))
    return result


def _build_supplementary(si, root, full_build, out_dir, result, log, markup):
    """Build the SM in the main document's build directory, so \\externaldocument resolves."""
    si_path = os.path.abspath(si)
    if not os.path.isfile(si_path):
        raise JCPUsageError(f"--si: no such file: {si_path}")
    si_name = os.path.basename(si_path)
    si_stem = os.path.splitext(si_name)[0]
    log(f"building supplementary material ({si_name})")

    si_cleaned, leftovers = markup.clean(read_text(si_path))
    for leftover in leftovers:
        result.add(ERROR, "sm", f"{leftover} still appears in the supplementary material")
    write_text(os.path.join(full_build, si_name), si_cleaned)

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


def _build_marked(root, build_root, out_dir, main_name, stem, result, log, si=None):
    """The manuscript *with* its revision markup, for the 'changes highlighted' upload.

    Returns ``(main_marked, sm_marked)``.  With ``si``, the supplementary material is marked
    too: a revision changes it as much as the main text, and the response to the referees
    points into both.  It is built after the main document in the same directory, so its
    ``\\externaldocument`` references resolve against the marked main ``.aux``.
    """
    log("building the marked copy")
    marked_dir = os.path.join(build_root, MARKED_BUILD)
    copy_project(root, marked_dir, skip_roots=[out_dir])
    built = run_latexmk(main_name, marked_dir)
    if not built.pdf_exists:
        result.add(WARNING, "marked", "the marked copy did not produce a PDF")
        return None, None
    target = os.path.join(out_dir, stem + "_marked.pdf")
    shutil.copy2(built.pdf_path, target)
    if si is None:
        return target, None

    si_relative = os.path.relpath(os.path.abspath(si), root)
    if si_relative.startswith(os.pardir):
        result.add(
            WARNING,
            "marked",
            f"{si} is outside the manuscript directory, so it has no marked copy",
        )
        return target, None
    si_name = os.path.basename(si_relative)
    si_stem = os.path.splitext(si_name)[0]
    log(f"building the marked copy of {si_relative}")
    si_built = run_latexmk(si_name, os.path.join(marked_dir, os.path.dirname(si_relative)))
    if not si_built.pdf_exists:
        result.add(WARNING, "marked", f"the marked copy of {si_relative} did not produce a PDF")
        return target, None
    si_target = os.path.join(out_dir, si_stem + "_marked.pdf")
    shutil.copy2(si_built.pdf_path, si_target)
    return target, si_target
