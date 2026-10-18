"""The whole pipeline against a real RevTeX manuscript. Skipped without a TeX installation.

This is the test that would catch a regression nobody else would: the package is only worth
anything if the files it ships compile *alone*, and that cannot be checked without compiling
them. The ``packaged`` fixture (in ``conftest.py``) does that once; everything here reads it.
"""

from pathlib import Path


def shipped_source(packaged):
    return (Path(packaged.source_dir) / "main.tex").read_text(encoding="utf-8")


def test_the_package_passes_every_hard_check(packaged):
    assert packaged.passed, "\n".join(check.render() for check in packaged.hard_failures)


def test_the_source_directory_is_flat_and_holds_no_bib(packaged):
    assert sorted(path.name for path in Path(packaged.source_dir).iterdir()) == [
        "fig1.pdf",
        "main.tex",
    ]


def test_nothing_from_a_comment_or_a_dropped_macro_survives(packaged):
    text = shipped_source(packaged)
    assert "SECRET" not in text
    assert "\\rev{" not in text and "revblock" not in text
    assert "\\input{" not in text


def test_the_shipped_source_is_pure_ascii(packaged):
    assert all(ord(character) < 128 for character in shipped_source(packaged))


def test_the_bibliography_travels_inside_the_tex(packaged):
    text = shipped_source(packaged)
    assert "\\begin{thebibliography}" in text
    assert "\\bibliography{references}" not in text


def test_the_en_dash_from_the_bib_is_reported_as_replaced(packaged):
    replaced = {replacement.character for replacement in packaged.replacements}
    assert "–" in replaced
    sources = {replacement.source for replacement in packaged.replacements}
    assert any(source and source.endswith("(from references)") for source in sources)


def test_the_author_pdf_and_the_sm_pdf_are_produced(packaged):
    assert packaged.pdf_path and Path(packaged.pdf_path).is_file()
    assert packaged.sm_pdf_path and Path(packaged.sm_pdf_path).is_file()


def test_flattening_did_not_change_the_document(packaged):
    built, verified = packaged.page_counts
    assert built == verified


def test_the_figure_was_renamed_and_the_reference_rewritten(packaged):
    text = shipped_source(packaged)
    assert "{fig1.pdf}" in text
    assert "figures/sub" not in text
    assert packaged.figure_map == [("figures/sub/f.pdf", "fig1.pdf")]


def test_the_alt_text_draft_lists_every_float(packaged):
    text = Path(packaged.alt_text_path).read_text()
    assert "Figure 1." in text and "Table 1." in text and "Figure S1." in text
    assert text.count("Alt text: TODO") == 3


def test_the_report_and_archive_are_written(packaged):
    report = Path(packaged.report_path).read_text()
    assert "PASSED" in report
    assert "fig1.pdf" in report
    assert packaged.zip_path and Path(packaged.zip_path).is_file()
