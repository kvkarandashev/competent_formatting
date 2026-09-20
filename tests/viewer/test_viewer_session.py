"""Seeding a session from CLI flags, and the loud-fail reconciliation contract."""

import pytest

from competent_formatting.viewer.config import CLEAN_PROFILE, load_config, save_config
from competent_formatting.viewer.session import (
    ReconciliationError,
    parse_labelled,
    reconcile,
    seed_config,
)


def make_spec(tmp_path, **overrides):
    main = tmp_path / "main.tex"
    main.write_text(r"\documentclass{article}\begin{document}x\end{document}")
    spec = {
        "docs": [("main", str(main))],
        "opened_macros": ["revised"],
        "removed_macros": ["collaboratorcomment"],
        "pre_scripts": [],
        "doc_pre_scripts": [],
        "host": "127.0.0.1",
        "port": 8000,
        "latex_cmd": "latexmk {main}",
    }
    spec.update(overrides)
    return spec


def test_parse_labelled_defaults_doc_label_to_stem():
    assert parse_labelled("/a/b/manuscript.tex", "--doc") == ("manuscript", "/a/b/manuscript.tex")
    assert parse_labelled("si=/a/b/sd.tex", "--doc") == ("si", "/a/b/sd.tex")


def test_doc_pre_script_requires_a_label():
    with pytest.raises(ValueError):
        parse_labelled("python make.py", "--doc_pre_script")


def test_seed_builds_full_and_clean_profiles(tmp_path):
    config = seed_config(make_spec(tmp_path))
    document = config.documents[0]
    assert document.profile_names == ["full", CLEAN_PROFILE]
    modes = {t.macro_name: t.mode for t in document.profile(CLEAN_PROFILE).transforms}
    assert modes == {"revised": "unwrap", "collaboratorcomment": "remove"}


def test_seed_without_macros_has_only_the_full_profile(tmp_path):
    config = seed_config(make_spec(tmp_path, opened_macros=[], removed_macros=[]))
    assert config.documents[0].profile_names == ["full"]


def test_doc_hook_for_unknown_label_is_rejected(tmp_path):
    spec = make_spec(tmp_path, doc_pre_scripts=[("nosuch", "python make.py")])
    with pytest.raises(ValueError, match="unknown document label"):
        seed_config(spec)


def test_config_roundtrips_through_toml(tmp_path):
    config = seed_config(make_spec(tmp_path))
    save_config(tmp_path, config)
    assert load_config(tmp_path) == config


def test_agreeing_flags_are_not_a_conflict(tmp_path):
    spec = make_spec(tmp_path)
    config = seed_config(spec)
    assert reconcile(config, spec, {"docs", "host", "port"}) == []


def test_rebinding_a_label_is_a_loud_conflict(tmp_path):
    spec = make_spec(tmp_path)
    config = seed_config(spec)
    other = tmp_path / "other.tex"
    other.write_text("x")
    clashing = make_spec(tmp_path, docs=[("main", str(other))])
    with pytest.raises(ReconciliationError) as error:
        reconcile(config, clashing, {"docs"})
    rendered = error.value.render()
    assert "--doc main" in rendered and "--overwrite_config" in rendered


def test_overwrite_config_lets_the_cli_win(tmp_path):
    spec = make_spec(tmp_path)
    config = seed_config(spec)
    other = tmp_path / "other.tex"
    other.write_text("x")
    changes = reconcile(
        config, make_spec(tmp_path, docs=[("main", str(other))]), {"docs"}, overwrite=True
    )
    assert changes and config.documents[0].main_tex == str(other.resolve())


def test_a_new_label_is_an_addition_not_a_conflict(tmp_path):
    spec = make_spec(tmp_path)
    config = seed_config(spec)
    extra = tmp_path / "sd.tex"
    extra.write_text("x")
    changes = reconcile(config, make_spec(tmp_path, docs=[("si", str(extra))]), {"docs"})
    assert len(config.documents) == 2
    assert any("added document" in change for change in changes)
    # A newly added document inherits the session's clean-profile macros.
    assert config.documents[1].profile(CLEAN_PROFILE) is not None


def test_scalar_flag_conflict_is_reported_with_both_values(tmp_path):
    config = seed_config(make_spec(tmp_path))
    with pytest.raises(ReconciliationError) as error:
        reconcile(config, make_spec(tmp_path, port=9999), {"port"})
    assert "--port: CLI=9999 vs workdir=8000" in error.value.render()


def test_flags_left_at_default_never_reset_stored_values(tmp_path):
    config = seed_config(make_spec(tmp_path, port=8123))
    # "port" absent from the explicit set: the persisted 8123 must survive.
    reconcile(config, make_spec(tmp_path, port=8000), set())
    assert config.port == 8123


def test_hooks_are_additive_and_deduplicated(tmp_path):
    config = seed_config(make_spec(tmp_path))
    spec = make_spec(tmp_path, pre_scripts=["python figures.py"])
    reconcile(config, spec, {"pre_scripts"})
    reconcile(config, spec, {"pre_scripts"})
    assert [hook.command for hook in config.global_hooks] == ["python figures.py"]


def test_new_macro_merges_into_the_clean_profile(tmp_path):
    config = seed_config(make_spec(tmp_path))
    spec = make_spec(tmp_path, opened_macros=["revised", "added_later"])
    reconcile(config, spec, {"opened_macros"})
    names = {t.macro_name for t in config.documents[0].profile(CLEAN_PROFILE).transforms}
    assert "added_later" in names and "collaboratorcomment" in names


def test_changing_a_macro_mode_is_a_conflict(tmp_path):
    config = seed_config(make_spec(tmp_path))
    spec = make_spec(tmp_path, opened_macros=["revised", "collaboratorcomment"], removed_macros=[])
    with pytest.raises(ReconciliationError):
        reconcile(config, spec, {"opened_macros", "removed_macros"})
