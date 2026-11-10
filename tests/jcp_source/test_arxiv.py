"""``cf_arxiv_source`` against the fixture manuscript and its SM. Skipped without TeX.

The SM ``\\ref``s the main text through ``\\externaldocument[M-]{main}``, which is exactly what
arXiv cannot compile; the package must resolve it and still verify in isolation.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from competent_formatting.processing.arxiv_source import build_arxiv_source
from competent_formatting.processing.source_package import Markup

MARKUP = Markup(
    opened_macros=("rev",), removed_macros=("authorcomment",), opened_envs=("revblock",)
)


@pytest.fixture(scope="module")
def packaged(compiled_project, tmp_path_factory):
    out = tmp_path_factory.mktemp("arxiv") / "package"
    return build_arxiv_source(
        [str(compiled_project / "main.tex"), str(compiled_project / "sm.tex")],
        str(out),
        markup=MARKUP,
        anc=[str(compiled_project / "references.bib")],
    )


def source(packaged, name):
    return (Path(packaged.source_dir) / name).read_text(encoding="utf-8")


def test_the_package_passes_every_hard_check(packaged):
    assert packaged.passed, "\n".join(check.render() for check in packaged.hard_failures)


def test_both_documents_and_their_figures_are_shipped_flat(packaged):
    shipped = sorted(path.name for path in Path(packaged.source_dir).iterdir())
    assert shipped == ["00README.json", "anc", "fig1.pdf", "main.tex", "sm.tex", "sm_fig1.pdf"]
    assert (Path(packaged.source_dir) / "anc" / "references.bib").is_file()


def test_the_readme_lists_the_top_level_files_in_order(packaged):
    readme = json.loads(source(packaged, "00README.json"))
    assert readme["process"] == {"compiler": "pdflatex"}
    assert [entry["filename"] for entry in readme["sources"]] == ["main.tex", "sm.tex"]
    assert {entry["usage"] for entry in readme["sources"]} == {"toplevel"}


def test_the_external_document_became_labels(packaged):
    text = source(packaged, "sm.tex")
    assert "\\externaldocument" not in text
    assert "\\newlabel{M-fig:square}{{1}" in text


def test_markup_and_comments_are_gone_from_both(packaged):
    for name in ("main.tex", "sm.tex"):
        text = source(packaged, name)
        assert "SECRET" not in text
        assert "\\rev{" not in text and "revblock" not in text


def test_both_bibliographies_are_inline_and_utf8_is_kept(packaged):
    text = source(packaged, "main.tex")
    assert "\\begin{thebibliography}" in text
    assert "–" in text  # arXiv's pdflatex reads UTF-8; no ASCII rewrite by default


def test_each_document_compiled_alone_to_the_same_page_count(packaged):
    for document in packaged.documents:
        assert document.pdf_path and Path(document.pdf_path).is_file()
        assert document.built_pages == document.verified_pages


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="needs pdftotext")
def test_the_sm_prints_the_main_figure_number(packaged):
    sm_pdf = next(d.pdf_path for d in packaged.documents if d.name == "sm.tex")
    text = subprocess.run(["pdftotext", sm_pdf, "-"], capture_output=True, text=True).stdout
    assert "See Fig. 1 of the main text." in text


def test_an_external_document_outside_the_package_is_a_hard_failure(compiled_project, tmp_path):
    result = build_arxiv_source(
        [str(compiled_project / "sm.tex")], str(tmp_path / "out"), markup=MARKUP
    )
    assert any(
        check.category == "references" and "not one of the packaged" in check.message
        for check in result.hard_failures
    )
