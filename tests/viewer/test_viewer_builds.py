"""Build materialization and the build-status rules.

These use stub compile commands rather than a real LaTeX run, so they stay fast
and do not need a TeX installation.
"""

import os

from competent_formatting.viewer.builds import build_dir_for, compile_build, materialize_build_dir
from competent_formatting.viewer.config import Document, MacroTransform, Profile

REVISED = MacroTransform(macro_name="revised", mode="unwrap")
WRITE_PDF = "python3 -c \"open('doc.pdf','w').write('%PDF-1.4')\""


def make_document(source_dir, profiles=None):
    source_dir.mkdir(parents=True, exist_ok=True)
    main = source_dir / "doc.tex"
    if not main.exists():
        main.write_text(r"\documentclass{article}")
    return Document(
        id="doc",
        label="doc",
        main_tex=str(main),
        profiles=profiles or [Profile(name="full")],
    )


def test_materialize_copies_sources_and_applies_transforms(tmp_path):
    source = tmp_path / "src"
    document = make_document(source)
    (source / "doc.tex").write_text(r"text \revised{kept}")
    (source / "figures").mkdir()
    (source / "figures" / "plot.pdf").write_bytes(b"%PDF-binary")
    build_dir = tmp_path / "build"

    materialize_build_dir(document, Profile(name="clean", transforms=[REVISED]), build_dir)

    assert (build_dir / "doc.tex").read_text() == "text kept"
    assert (build_dir / "figures" / "plot.pdf").read_bytes() == b"%PDF-binary"
    assert (source / "doc.tex").read_text() == r"text \revised{kept}"  # never mutated


def test_unchanged_files_keep_their_mtime_so_latexmk_stays_incremental(tmp_path):
    source = tmp_path / "src"
    document = make_document(source)
    build_dir = tmp_path / "build"
    profile = Profile(name="full")

    materialize_build_dir(document, profile, build_dir)
    first = (build_dir / "doc.tex").stat().st_mtime_ns
    materialize_build_dir(document, profile, build_dir)
    assert (build_dir / "doc.tex").stat().st_mtime_ns == first


def test_deleted_sources_are_pruned_but_compiler_artifacts_survive(tmp_path):
    source = tmp_path / "src"
    document = make_document(source)
    (source / "extra.tex").write_text("x")
    build_dir = tmp_path / "build"
    profile = Profile(name="full")

    materialize_build_dir(document, profile, build_dir)
    (build_dir / "doc.aux").write_text("aux state")
    (source / "extra.tex").unlink()
    materialize_build_dir(document, profile, build_dir)

    assert not (build_dir / "extra.tex").exists()
    assert (build_dir / "doc.aux").exists()


def test_aux_files_in_the_source_dir_are_not_copied(tmp_path):
    source = tmp_path / "src"
    document = make_document(source)
    (source / "doc.aux").write_text("stale aux from the user's own run")
    build_dir = tmp_path / "build"
    materialize_build_dir(document, Profile(name="full"), build_dir)
    assert not (build_dir / "doc.aux").exists()


def test_a_workdir_nested_in_the_sources_is_not_copied_into_itself(tmp_path):
    source = tmp_path / "src"
    document = make_document(source)
    workdir = source / "session"
    (workdir / "build").mkdir(parents=True)
    (workdir / "build" / "junk.tex").write_text("should not be copied")
    build_dir = build_dir_for(workdir, "doc", "full")
    materialize_build_dir(document, Profile(name="full"), build_dir, skip_roots=[workdir])
    assert not (build_dir / "session").exists()


def test_status_ok_when_the_driver_succeeds(tmp_path):
    document = make_document(tmp_path / "src")
    result = compile_build(document, document.profiles[0], tmp_path / "wd", WRITE_PDF)
    assert result.status == "ok"
    assert result.ok and result.pdf_path.is_file()


def test_status_warning_when_the_driver_fails_but_the_pdf_is_current(tmp_path):
    # The real case: latexmk exits 12 on a BibTeX error yet emits a good PDF.
    document = make_document(tmp_path / "src")
    command = f"{WRITE_PDF}; exit 12"
    result = compile_build(document, document.profiles[0], tmp_path / "wd", command)
    assert result.status == "warning"
    assert result.ok  # the PDF is still shown
    assert "12" in result.message


def test_a_no_op_rerun_of_a_failing_driver_does_not_regress_to_failed(tmp_path):
    # latexmk re-reports a cached BibTeX error on every rerun without doing
    # work; that must not turn a good build into a "failed" one.
    document = make_document(tmp_path / "src")
    workdir = tmp_path / "wd"
    compile_build(document, document.profiles[0], workdir, f"{WRITE_PDF}; exit 12")
    result = compile_build(document, document.profiles[0], workdir, "exit 12")
    assert result.status == "warning"


def test_status_failed_when_no_pdf_is_produced(tmp_path):
    document = make_document(tmp_path / "src")
    result = compile_build(document, document.profiles[0], tmp_path / "wd", "exit 1")
    assert result.status == "failed"
    assert not result.ok


def test_status_failed_when_the_pdf_is_older_than_the_sources(tmp_path):
    document = make_document(tmp_path / "src")
    workdir = tmp_path / "wd"
    compile_build(document, document.profiles[0], workdir, WRITE_PDF)
    pdf = build_dir_for(workdir, "doc", "full") / "doc.pdf"
    os.utime(pdf, (1, 1))  # pretend it predates the sources
    result = compile_build(document, document.profiles[0], workdir, "exit 1")
    assert result.status == "failed"


def test_logs_are_written_where_the_ui_advertises_them(tmp_path):
    document = make_document(tmp_path / "src")
    workdir = tmp_path / "wd"
    result = compile_build(document, document.profiles[0], workdir, WRITE_PDF)
    assert result.driver_log_path == workdir / "logs" / "doc__full.log"
    assert result.driver_log_path.is_file()


def test_compile_streams_lines_to_the_callback(tmp_path):
    document = make_document(tmp_path / "src")
    seen = []
    compile_build(
        document,
        document.profiles[0],
        tmp_path / "wd",
        "echo first; echo second",
        on_line=seen.append,
    )
    assert "first" in seen and "second" in seen
