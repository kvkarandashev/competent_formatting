"""Packaging decisions that need no TeX: the output directory, and the bibliography splice."""

import pytest

from competent_formatting.processing.jcp_source import (
    JCPSourceError,
    JCPUsageError,
    drop_bibliographystyle,
    find_bibliography,
    inline_bibliography,
    prepare_out_dir,
)

# Every character sequence that a naive re.sub would eat.
NASTY_BBL = r"""\begin{thebibliography}{2}
\bibitem{a}
A.~Author, \emph{A title with \\ and \1 and \g<0> in it}, \textbackslash{} 2026.
\bibitem{b}
B.~Author, 100\% of the way, 2026.
\end{thebibliography}
"""


def test_the_bbl_is_spliced_in_literally():
    text = "before\n\\bibliography{references}\nafter\n"
    span, databases = find_bibliography(text)
    assert databases == ["references"]
    result = inline_bibliography(text, span, NASTY_BBL)
    assert r"\\ and \1 and \g<0>" in result
    assert r"\bibliography{references}" not in result
    assert result.startswith("before\n") and result.endswith("after\n")


def test_bibliographystyle_goes_with_it():
    text = "\\bibliographystyle{aipnum4-2}\n\\bibliography{refs}\n"
    assert "bibliographystyle" not in drop_bibliographystyle(text)


def test_two_bibliographies_are_refused():
    with pytest.raises(JCPSourceError, match="exactly one"):
        find_bibliography("\\bibliography{a}\n\\bibliography{b}\n")


def test_biblatex_is_refused_by_name():
    with pytest.raises(JCPSourceError, match="biblatex"):
        find_bibliography("\\addbibresource{refs.bib}\n\\printbibliography\n")


def test_a_commented_out_bibliography_does_not_count():
    span, _ = find_bibliography("% \\bibliography{old}\n\\bibliography{new}\n")
    assert span is not None


def test_the_output_directory_may_not_be_the_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(JCPUsageError, match="manuscript directory itself"):
        prepare_out_dir(str(project), str(project))
    with pytest.raises(JCPUsageError, match="contains the manuscript"):
        prepare_out_dir(str(tmp_path), str(project))


def test_a_non_empty_output_directory_needs_force(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "report.md").write_text("old")
    with pytest.raises(JCPUsageError, match="--force"):
        prepare_out_dir(str(out), str(tmp_path / "project"))
    prepare_out_dir(str(out), str(tmp_path / "project"), force=True)
    assert list(out.iterdir()) == []


def test_force_refuses_to_delete_files_it_did_not_write(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "thesis_chapter.tex").write_text("months of work")
    with pytest.raises(JCPUsageError, match="did not write"):
        prepare_out_dir(str(out), str(tmp_path / "project"), force=True)
    assert (out / "thesis_chapter.tex").is_file()
