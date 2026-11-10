"""Turn one or more working documents into a source directory arXiv will compile.

arXiv recompiles whatever it is given, so the upload is source, not PDF: every top-level
``.tex`` (a manuscript and its supplementary material, say), the figures they use, and the
bibliography as a ``.bbl`` -- arXiv only runs BibTeX when no ``.bbl`` is uploaded. It compiles
each top-level file on its own and concatenates the PDFs in the order a ``00README.json``
lists them (https://info.arxiv.org/help/00README.html).

Two consequences shape this module beyond what :mod:`.source_package` already does:

- **Cross-document references.** A supplement that ``\\ref``s the main text through
  ``xr``/``\\externaldocument`` loses those references on arXiv ("the external file will be
  lost", says arXiv's own help). They are resolved here instead: the ``\\externaldocument``
  call becomes the labels it would have read (:mod:`.external_labels`), taken from the cleaned
  build of the referenced document, which must therefore be one of the packaged documents.
- **The source is public.** arXiv serves it to anyone, so comments -- which is where internal
  notes live -- are stripped by default, as is the revision markup the caller names.

What is *not* done, unlike for a journal: no ASCII normalisation (arXiv's pdflatex reads
UTF-8; ``ascii=True`` brings it back), and none of AIP's figure and prose checks.
"""

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .external_labels import resolve_external_documents
from .jcp_checks import ERROR, INFO, WARNING, parse_class_and_packages
from .latex_build import require_executable
from .source_package import (
    BUILD_DIRNAME,
    FULL_BUILD,
    REPORT_NAME,
    SOURCE_DIRNAME,
    VERIFY_BUILD,
    ZIP_NAME,
    Markup,
    SourcePackageResult,
    SourcePackageUsageError,
    collect_figures,
    compare_page_counts,
    copy_project,
    full_build,
    make_zip,
    prepare_document,
    prepare_out_dir,
    read_text,
    render_report,
    ship_local_styles,
    splice_bibliography,
    verify_in_isolation,
    write_text,
)

README_NAME = "00README.json"
ANC_DIRNAME = "anc"
ARTIFACT_NAMES = {SOURCE_DIRNAME, BUILD_DIRNAME, REPORT_NAME, ZIP_NAME}

# arXiv's usual per-submission cap; larger uploads need to be arranged with them.
SIZE_LIMIT_MB = 50


@dataclass
class ArxivDocument:
    path: str  # absolute path of the working .tex
    name: str  # file name in the package
    figure_prefix: str
    built_pages: Optional[int] = None
    verified_pages: Optional[int] = None
    pdf_path: Optional[str] = None

    @property
    def stem(self):
        return os.path.splitext(self.name)[0]


@dataclass(kw_only=True)
class ArxivSourceResult(SourcePackageResult):
    documents: List[ArxivDocument] = field(default_factory=list)
    anc: List[Tuple[str, str]] = field(default_factory=list)  # (source, shipped path)
    readme_path: Optional[str] = None

    report_title = "arXiv source package"

    def report_header(self):
        lines = [f"- output directory: `{self.out_dir}`"]
        lines.append(
            "- upload: the contents of `source/`"
            + (f", or `{os.path.basename(self.zip_path)}`" if self.zip_path else "")
        )
        for document in self.documents:
            line = f"- top-level `{document.name}`"
            if document.pdf_path:
                line += f" -> `{os.path.basename(document.pdf_path)}`"
            lines.append(line)
        if self.readme_path:
            lines.append(f"- `{README_NAME}` lists them in this order (arXiv's PDF order)")
        for source, shipped in self.anc:
            lines.append(f"- ancillary `{shipped}` (from `{source}`)")
        return lines

    def report_footer(self):
        lines = ["## Page counts", ""]
        for document in self.documents:
            lines.append(
                f"- `{document.name}`: full build {document.built_pages}, verified flat build "
                f"{document.verified_pages}"
            )
        return lines + [""]


def _documents(tex_files, figure_prefixes):
    """Validate the requested documents and give each a unique name and figure prefix."""
    if not tex_files:
        raise SourcePackageUsageError("name at least one .tex file to package")
    if figure_prefixes and len(figure_prefixes) != len(tex_files):
        raise SourcePackageUsageError(
            f"{len(figure_prefixes)} figure prefix(es) for {len(tex_files)} document(s); give "
            "one per document, in the same order, or none for the defaults"
        )
    documents = []
    for index, tex in enumerate(tex_files):
        path = os.path.abspath(tex)
        if not os.path.isfile(path):
            raise SourcePackageUsageError(f"no such file: {path}")
        name = os.path.basename(path)
        stem = os.path.splitext(name)[0]
        if figure_prefixes:
            prefix = figure_prefixes[index]
        else:
            prefix = "fig" if index == 0 else f"{stem}_fig"
        documents.append(ArxivDocument(path=path, name=name, figure_prefix=prefix))

    for attribute, what in (("name", "file name"), ("figure_prefix", "figure prefix")):
        values = [getattr(document, attribute) for document in documents]
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise SourcePackageUsageError(
                f"two documents would share the {what} {duplicates[0]!r} in the flat package"
            )
    root = os.path.dirname(documents[0].path)
    for document in documents[1:]:
        if os.path.commonpath([root, document.path]) != root:
            raise SourcePackageUsageError(
                f"{document.path} is outside {root}, the directory of the first document; "
                "the documents are built together, so they must share one project tree"
            )
    return root, documents


def _aux_lookup(document, documents, root, full_dir):
    """``aux_for(name)`` for :func:`resolve_external_documents`, scoped to the package."""
    by_location = {
        os.path.splitext(os.path.relpath(other.path, root))[0]: other for other in documents
    }

    def aux_for(name):
        relative = os.path.relpath(os.path.join(os.path.dirname(document.path), name), root)
        target = by_location.get(os.path.splitext(os.path.normpath(relative))[0])
        if target is None or target is document:
            return None
        aux = os.path.join(full_dir, os.path.dirname(os.path.relpath(target.path, root)))
        aux = os.path.join(aux, target.stem + ".aux")
        return read_text(aux) if os.path.isfile(aux) else None

    return aux_for


def _copy_anc(anc, source_dir, result):
    """Ancillary files go to ``anc/``, which arXiv lists beside the paper but never compiles."""
    if not anc:
        return
    anc_dir = os.path.join(source_dir, ANC_DIRNAME)
    os.makedirs(anc_dir, exist_ok=True)
    for item in anc:
        path = os.path.abspath(item)
        target = os.path.join(anc_dir, os.path.basename(path.rstrip(os.sep)))
        if os.path.exists(target):
            raise SourcePackageUsageError(f"two ancillary files are both named {target}")
        if os.path.isdir(path):
            shutil.copytree(path, target)
        elif os.path.isfile(path):
            shutil.copy2(path, target)
        else:
            raise SourcePackageUsageError(f"--anc: no such file or directory: {path}")
        result.anc.append((item, os.path.relpath(target, source_dir)))


def readme(documents, compiler="pdflatex"):
    """``00README.json``: the compiler, and the top-level files in their PDF order."""
    return (
        json.dumps(
            {
                "spec_version": 1,
                "process": {"compiler": compiler},
                "sources": [
                    {"filename": document.name, "usage": "toplevel"} for document in documents
                ],
            },
            indent=2,
        )
        + "\n"
    )


def _directory_size_mb(directory):
    total = 0
    for parent, _, names in os.walk(directory):
        total += sum(os.path.getsize(os.path.join(parent, name)) for name in names)
    return total / 1e6


def build_arxiv_source(
    tex_files,
    out_dir,
    markup=Markup(),
    bbl="inline",
    keep_comments=False,
    figure_prefixes=(),
    anc=(),
    ascii=False,
    write_readme=True,
    make_archive=True,
    force=False,
    log=lambda message: None,
):
    """Assemble and verify an arXiv upload of ``tex_files``, in that (PDF) order."""
    require_executable("pdflatex")
    require_executable("latexmk")
    root, documents = _documents(list(tex_files), list(figure_prefixes))

    out_dir = prepare_out_dir(out_dir, root, ARTIFACT_NAMES, force=force)
    source_dir = os.path.join(out_dir, SOURCE_DIRNAME)
    os.makedirs(source_dir, exist_ok=True)
    build_root = os.path.join(out_dir, BUILD_DIRNAME)
    full_dir = os.path.join(build_root, FULL_BUILD)
    result = ArxivSourceResult(out_dir=out_dir, documents=documents)

    # 1. flatten and clean every document, then build them all, in order, so a later
    #    document's \externaldocument finds the earlier one's .aux -----------------
    texts = {}
    for document in documents:
        log("flattening " + document.name)
        texts[document.name] = prepare_document(
            document.path,
            os.path.dirname(document.path),
            markup,
            result,
            keep_comments=keep_comments,
            ascii=ascii,
            label=document.name,
        )
    log("building with latexmk (BibTeX) in " + os.path.relpath(full_dir, out_dir))
    copy_project(root, full_dir, skip_roots=[out_dir])
    for document in documents:
        relative = os.path.relpath(document.path, root)
        write_text(os.path.join(full_dir, relative), texts[document.name])
    for document in documents:
        relative = os.path.relpath(document.path, root)
        cwd = os.path.join(full_dir, os.path.dirname(relative))
        _, document.built_pages = full_build(document.name, cwd, result, label=document.name)

    for document in documents:
        text = texts[document.name]
        relative_dir = os.path.dirname(os.path.relpath(document.path, root))
        document_root = os.path.dirname(document.path)

        # 2. cross-document references ---------------------------------------------
        text, resolved, unresolved = resolve_external_documents(
            text, _aux_lookup(document, documents, root, full_dir)
        )
        for external, count in resolved:
            result.add(
                INFO,
                "references",
                f"{document.name}: \\externaldocument[{external.prefix}]{{{external.name}}} "
                f"replaced by its {count} labels; references into it print as plain numbers, "
                "without links",
            )
        for external in unresolved:
            result.add(
                ERROR,
                "references",
                f"{document.name}: \\externaldocument{{{external.name}}} is not one of the "
                "packaged documents (or did not build); arXiv will not have its .aux, so add "
                "its .tex to the list",
            )

        # 3. figures, bibliography, local style files -------------------------------
        log(f"collecting figures of {document.name}")
        text = collect_figures(text, document_root, source_dir, document.figure_prefix, result)
        bbl_path = os.path.join(full_dir, relative_dir, document.stem + ".bbl")
        text = splice_bibliography(
            text, bbl_path, bbl, document_root, source_dir, result, ascii=ascii, missing_level=INFO
        )
        ship_local_styles(parse_class_and_packages(text), document_root, source_dir, result)
        write_text(os.path.join(source_dir, document.name), text)

    # 4. ancillary files and the 00README ------------------------------------------
    _copy_anc(anc, source_dir, result)
    if write_readme:
        result.readme_path = os.path.join(source_dir, README_NAME)
        write_text(result.readme_path, readme(documents))

    # 5. the guarantee: the shipped files, alone, pdflatex only, in arXiv's order ----
    log("verifying the package in an empty directory (pdflatex only)")
    outcomes = verify_in_isolation(
        source_dir,
        os.path.join(build_root, VERIFY_BUILD),
        [document.name for document in documents],
        result,
        label_each=len(documents) > 1,
    )
    for document in documents:
        verified, document.verified_pages = outcomes[document.name]
        compare_page_counts(
            document.built_pages, document.verified_pages, result, label=document.name
        )
        if verified.pdf_exists:
            document.pdf_path = os.path.join(out_dir, document.stem + ".pdf")
            shutil.copy2(verified.pdf_path, document.pdf_path)

    size = _directory_size_mb(source_dir)
    if size > SIZE_LIMIT_MB:
        result.add(
            WARNING,
            "size",
            f"source/ holds {size:.1f} MB, over arXiv's usual {SIZE_LIMIT_MB} MB limit",
        )

    # 6. archive and report --------------------------------------------------------
    if make_archive:
        result.zip_path = make_zip(source_dir, os.path.join(out_dir, ZIP_NAME))
    result.report_path = os.path.join(out_dir, REPORT_NAME)
    write_text(result.report_path, render_report(result))
    return result
