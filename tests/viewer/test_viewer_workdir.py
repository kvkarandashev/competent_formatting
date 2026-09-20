"""Discovery of the project-local ``.cf_view`` session directory, and the
relative path storage that lets such a directory be committed and cloned."""

import os
import shutil

from competent_formatting.viewer.config import (
    WORKDIR_DIRNAME,
    Document,
    Profile,
    SessionConfig,
    default_workdir,
    find_workdir,
    load_config,
    save_config,
)


def make_project(tmp_path, name="project"):
    """A manuscript directory holding main.tex and a .cf_view session."""
    project = tmp_path / name
    (project / WORKDIR_DIRNAME).mkdir(parents=True)
    (project / "main.tex").write_text(r"\documentclass{article}")
    return project


def seeded_config(project):
    return SessionConfig(
        documents=[
            Document(
                id="main",
                label="main",
                main_tex=str(project / "main.tex"),
                profiles=[Profile(name="full")],
            )
        ]
    )


def test_find_workdir_locates_a_session_in_the_current_directory(tmp_path):
    project = make_project(tmp_path)
    save_config(project / WORKDIR_DIRNAME, seeded_config(project))
    assert find_workdir(project) == project / WORKDIR_DIRNAME


def test_find_workdir_walks_up_from_a_subdirectory(tmp_path):
    project = make_project(tmp_path)
    save_config(project / WORKDIR_DIRNAME, seeded_config(project))
    deep = project / "tables" / "CPU_times"
    deep.mkdir(parents=True)
    assert find_workdir(deep) == project / WORKDIR_DIRNAME


def test_find_workdir_returns_none_when_there_is_no_session(tmp_path):
    empty = tmp_path / "unrelated"
    empty.mkdir()
    assert find_workdir(empty) is None


def test_a_session_directory_without_a_config_is_not_discovered(tmp_path):
    project = make_project(tmp_path)  # .cf_view exists but holds no config
    assert find_workdir(project) is None


def test_default_workdir_falls_back_to_cwd_when_nothing_is_discovered(tmp_path):
    empty = tmp_path / "fresh"
    empty.mkdir()
    assert default_workdir(empty) == empty / WORKDIR_DIRNAME


def test_documents_inside_the_project_are_stored_relative(tmp_path):
    project = make_project(tmp_path)
    workdir = project / WORKDIR_DIRNAME
    save_config(workdir, seeded_config(project))
    stored = (workdir / "competent_viewer.toml").read_text()
    assert 'main_tex = "../main.tex"' in stored
    assert str(tmp_path) not in stored  # no absolute path leaked into the file


def test_relative_paths_resolve_back_to_absolute_on_load(tmp_path):
    project = make_project(tmp_path)
    workdir = project / WORKDIR_DIRNAME
    save_config(workdir, seeded_config(project))
    loaded = load_config(workdir)
    assert loaded.documents[0].main_tex == str(project / "main.tex")


def test_a_committed_session_survives_the_project_being_moved(tmp_path):
    project = make_project(tmp_path, "original")
    save_config(project / WORKDIR_DIRNAME, seeded_config(project))

    moved = tmp_path / "cloned-elsewhere"
    shutil.move(str(project), str(moved))

    loaded = load_config(moved / WORKDIR_DIRNAME)
    assert loaded.documents[0].main_tex == str(moved / "main.tex")
    assert os.path.isfile(loaded.documents[0].main_tex)


def test_documents_outside_the_project_stay_absolute(tmp_path):
    project = make_project(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "other.tex").write_text("x")
    config = SessionConfig(
        documents=[
            Document(
                id="other",
                label="other",
                main_tex=str(outside / "other.tex"),
                profiles=[Profile(name="full")],
            )
        ]
    )
    workdir = project / WORKDIR_DIRNAME
    save_config(workdir, config)
    assert str(outside / "other.tex") in (workdir / "competent_viewer.toml").read_text()
    assert load_config(workdir).documents[0].main_tex == str(outside / "other.tex")
