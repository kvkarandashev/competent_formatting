"""Stripping revision markup written as macros and as environments, and the ASCII pass."""

import pytest

from competent_formatting.processing.macro_removal import remove_macros
from competent_formatting.processing.unicode_ascii import (
    UnmappedCharacterError,
    latex_for,
    to_ascii,
)

DEFINITIONS = r"""\newif\ifshowrevisions
\showrevisionstrue
\ifshowrevisions
  \newcommand{\rev}[1]{{\color{red}#1}}
  \newenvironment{revblock}{\color{red}}{}
\else
  \newcommand{\rev}[1]{#1}
  \newenvironment{revblock}{}{}
\fi
"""


def clean(text, **kwargs):
    return remove_macros(text, **kwargs)


def test_an_opened_environment_keeps_its_body():
    source = r"before \begin{revblock}kept\end{revblock} after"
    assert clean(source, opened_envs=["revblock"]) == "before kept after"


def test_a_removed_environment_takes_its_body_with_it():
    source = r"before \begin{draft}gone\end{draft} after"
    assert "gone" not in clean(source, removed_envs=["draft"])


def test_environment_definitions_are_dropped_in_both_branches():
    result = clean(DEFINITIONS, opened_envs=["revblock"], opened_fields=["rev"])
    assert "newcommand" not in result
    assert "newenvironment" not in result
    # The conditional itself is left alone: evaluating \if is TeX's job, and an empty
    # conditional compiles.
    assert "\\ifshowrevisions" in result and "\\else" in result and "\\fi" in result


def test_nested_environments_are_unwrapped_from_the_inside_out():
    source = r"\begin{revblock}a \begin{revblock}b\end{revblock} c\end{revblock}"
    assert clean(source, opened_envs=["revblock"]) == "a b c"


def test_a_macro_inside_an_opened_environment_is_still_stripped():
    source = r"\begin{revblock}kept \rev{also kept} \note{gone}\end{revblock}"
    result = clean(
        source, opened_envs=["revblock"], opened_fields=["rev"], removed_fields=["note"]
    )
    assert result == "kept also kept "


def test_an_environment_inside_an_opened_macro_is_still_stripped():
    source = r"\rev{outer \begin{revblock}inner\end{revblock}}"
    assert clean(source, opened_fields=["rev"], opened_envs=["revblock"]) == "outer inner"


def test_unrelated_environments_survive_untouched():
    source = "\\begin{figure}[ht]\n\\includegraphics{a}\n\\end{figure}"
    assert clean(source, opened_envs=["revblock"]) == source


def test_the_old_macro_only_call_still_works():
    # Backwards compatibility: every existing caller passes these two keywords only.
    source = r"\revised{kept} \comment{gone}"
    assert clean(source, opened_fields=["revised"], removed_fields=["comment"]) == "kept "


# ------------------------------------------------------------------ non-ASCII


@pytest.mark.parametrize(
    "character,expected",
    [
        ("\u2013", "--"),
        ("\u2014", "---"),
        ("\u2500", "---"),
        ("\u2010", "-"),
        ("\u2212", r"\ensuremath{-}"),
        ("\u2019", "'"),
        ("\u201c", "``"),
        ("\u201d", "''"),
        ("\u223c", r"\ensuremath{\sim}"),
        ("\u00d7", r"\ensuremath{\times}"),
        ("\u00b1", r"\ensuremath{\pm}"),
        ("\u00b0", r"\ensuremath{^\circ}"),
        ("\u00a0", "~"),
        ("\u00e4", '{\\"a}'),
        ("\u00e1", "{\\'a}"),
        ("\u00f8", r"{\o}"),
        ("\u0142", r"{\l}"),
        ("\u03b1", r"\ensuremath{\alpha}"),
        ("\u03a9", r"\ensuremath{\Omega}"),
    ],
)
def test_the_mapping_covers_what_manuscripts_contain(character, expected):
    assert latex_for(character) == expected


def test_replacements_are_reported_with_their_source():
    class Origin:
        path, line = "references.bib", 12

    text, replacements = to_ascii("a \u2013 b\n", origin_of_line=lambda number: Origin)
    assert text == "a -- b\n"
    assert replacements[0].source == "references.bib:12"


def test_an_unmapped_character_is_an_error_listing_all_of_them():
    with pytest.raises(UnmappedCharacterError) as raised:
        to_ascii("\u2638 and \u262f")
    assert len(raised.value.unmapped) == 2
    assert "U+2638" in raised.value.render()


def test_verbatim_content_is_left_alone():
    source = "\\url{http://a/\u00e9}\n"
    text, replacements = to_ascii(source)
    assert text == source and replacements == []
