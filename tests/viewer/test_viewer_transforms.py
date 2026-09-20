"""The clean-profile transform: unwrap revision macros, delete comment macros."""

import pytest

from competent_formatting.viewer.config import MacroTransform
from competent_formatting.viewer.transforms import (
    TransformError,
    apply_transforms,
    split_macro_transforms,
    transform_source_text,
)

REVISED = MacroTransform(macro_name="revised", mode="unwrap")
COMMENT = MacroTransform(macro_name="collaboratorcomment", mode="remove")


def test_unwrap_keeps_content_and_drops_macro():
    source = r"before \revised{kept text} after"
    assert transform_source_text(source, [REVISED]) == "before kept text after"


def test_remove_drops_macro_and_its_content():
    source = r"before \collaboratorcomment{gone} after"
    assert "gone" not in transform_source_text(source, [COMMENT])


def test_macro_definitions_are_stripped_too():
    source = "\n".join(
        [
            r"\newcommand{\revised}[1]{\textcolor{red}{#1}}",
            r"\newcommand{\collaboratorcomment}[1]{\textbf{#1}}",
            r"prose \revised{KEPTWORD} \collaboratorcomment{DROPPEDWORD}",
        ]
    )
    result = transform_source_text(source, [REVISED, COMMENT])
    assert "newcommand" not in result
    assert "KEPTWORD" in result
    assert "DROPPEDWORD" not in result


def test_unrelated_macros_survive():
    source = r"\emph{kept} \Ntrain \revised{also kept}"
    result = transform_source_text(source, [REVISED])
    assert r"\emph{kept}" in result and r"\Ntrain" in result


def test_no_transforms_is_a_verbatim_no_op():
    source = r"\revised{unchanged} \collaboratorcomment{also unchanged}"
    assert transform_source_text(source, []) == source


def test_split_macro_transforms_maps_onto_remove_macros_fields():
    removed, opened = split_macro_transforms([REVISED, COMMENT])
    assert removed == ["collaboratorcomment"]
    assert opened == ["revised"]


def test_apply_transforms_only_touches_tex_files(tmp_path):
    (tmp_path / "a.tex").write_text(r"\revised{x}")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.tex").write_text(r"\revised{y}")
    (tmp_path / "notes.txt").write_text(r"\revised{z}")
    changed = apply_transforms(tmp_path, [REVISED])
    assert {path.name for path in changed} == {"a.tex", "b.tex"}
    assert (tmp_path / "notes.txt").read_text() == r"\revised{z}"


def test_argumentless_revision_macro_is_reported_as_transform_error(tmp_path):
    # pylatexenc tolerates an unclosed brace, but a special macro with no
    # argument at all cannot be unwrapped and must not fail silently.
    (tmp_path / "broken.tex").write_text(r"trailing \revised")
    with pytest.raises(TransformError):
        apply_transforms(tmp_path, [REVISED])


def test_unclosed_brace_is_tolerated_like_the_cli(tmp_path):
    (tmp_path / "loose.tex").write_text(r"\revised{unclosed")
    apply_transforms(tmp_path, [REVISED])
    assert (tmp_path / "loose.tex").read_text() == "unclosed"
