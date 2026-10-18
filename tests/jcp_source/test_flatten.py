"""Flattening, comment stripping and figure renaming -- no TeX installation needed."""

import pytest

from competent_formatting.processing.flatten import (
    FlattenError,
    assign_graphic_names,
    find_graphics,
    flatten,
    graphicspath_directories,
    resolve_graphic,
    rewrite_graphics,
)
from competent_formatting.processing.latex_spans import strip_comments, strip_comments_by_line


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ comments


@pytest.mark.parametrize(
    "source,expected",
    [
        # The % is what joins the lines; dropping it would insert a space.
        ("foo%comment\nbar\n", "foo%\nbar\n"),
        # A space is already there, so the whole comment goes.
        ("foo %comment\nbar\n", "foo \nbar\n"),
        # A comment-only line leaves nothing behind, not a blank line.
        ("a\n  % whole line\nb\n", "a\nb\n"),
        (r"100\% done % note" + "\nx\n", "100\\% done \nx\n"),
        ("\\url{http://a.b/%7Euser}\ny % c\n", "\\url{http://a.b/%7Euser}\ny \n"),
        ("\\verb|50% off| % c\n", "\\verb|50% off| \n"),
        ("\\href{http://a/%7Eb}{text} % c\n", "\\href{http://a/%7Eb}{text} \n"),
        (
            "\\begin{verbatim}\n50% off\n\\end{verbatim}\n% gone\nz\n",
            "\\begin{verbatim}\n50% off\n\\end{verbatim}\nz\n",
        ),
        (
            "\\begin{lstlisting}\nx = 1 % kept\n\\end{lstlisting}\n",
            "\\begin{lstlisting}\nx = 1 % kept\n\\end{lstlisting}\n",
        ),
    ],
)
def test_comment_stripping_cases(source, expected):
    assert strip_comments(source) == expected


def test_stripping_keeps_the_original_line_numbers():
    kept = strip_comments_by_line("a\n% drop\nb % keep\nc%join\n")
    assert kept == [(1, "a"), (3, "b "), (4, "c%")]


# ------------------------------------------------------------------ flattening


def test_nested_inputs_are_inlined_with_provenance(tmp_path):
    write(tmp_path, "sections/one.tex", "First section.\n\\input{sections/two}\n")
    write(tmp_path, "sections/two.tex", "Second section.\n")
    main = write(tmp_path, "main.tex", "Start\n\\input{sections/one}\nEnd\n")

    flat = flatten(main)

    assert "Start" in flat.text and "Second section." in flat.text
    assert "\\input" not in flat.text
    assert flat.inputs == ["sections/one.tex", "sections/two.tex"]
    line = flat.text.splitlines().index("Second section.") + 1
    assert flat.origin_of_line(line) == ("sections/two.tex", 1)


def test_an_input_inside_a_comment_is_not_inlined(tmp_path):
    write(tmp_path, "other.tex", "SHOULD NOT APPEAR\n")
    main = write(tmp_path, "main.tex", "text\n% \\input{other}\nmore\n")
    assert "SHOULD NOT APPEAR" not in flatten(main).text


def test_an_input_cycle_is_an_error_not_a_hang(tmp_path):
    write(tmp_path, "a.tex", "\\input{b}\n")
    write(tmp_path, "b.tex", "\\input{a}\n")
    main = write(tmp_path, "main.tex", "\\input{a}\n")
    with pytest.raises(FlattenError, match="cycle"):
        flatten(main)


def test_a_missing_input_names_the_file_and_line(tmp_path):
    main = write(tmp_path, "main.tex", "one\n\\input{nowhere}\n")
    with pytest.raises(FlattenError, match=r"main\.tex:2"):
        flatten(main)


def test_include_keeps_the_page_break_it_implied(tmp_path):
    write(tmp_path, "chapter.tex", "Chapter text.\n")
    main = write(tmp_path, "main.tex", "before\n\\include{chapter}\nafter\n")
    assert flatten(main).text.count("\\clearpage") == 2


def test_an_unsupported_input_mechanism_is_refused(tmp_path):
    main = write(tmp_path, "main.tex", "\\subfile{part}\n")
    with pytest.raises(FlattenError, match="subfile"):
        flatten(main)


def test_text_around_an_inline_input_keeps_its_line(tmp_path):
    write(tmp_path, "mid.tex", "MIDDLE")
    main = write(tmp_path, "main.tex", "before \\input{mid} after\n")
    assert flatten(main).text.splitlines()[0] == "before MIDDLE after"


def test_comments_can_be_kept(tmp_path):
    main = write(tmp_path, "main.tex", "text % a comment\n")
    assert "a comment" in flatten(main, keep_comments=True).text
    assert "a comment" not in flatten(main).text


# ------------------------------------------------------------------ figures


FIGURES = r"""
\graphicspath{{alt/}}
\begin{figure}
\includegraphics[width=0.5\textwidth]{one}
\end{figure}
\begin{figure*}
\includegraphics{two.png}
\includegraphics{three}
\end{figure*}
\includegraphics{one}
"""


def test_graphics_are_numbered_by_their_float(tmp_path):
    uses = find_graphics(FIGURES)
    assert [use.float_number for use in uses] == [1, 2, 2, None]
    assert [use.suffix for use in uses] == ["", "a", "b", ""]

    resolved = ["/p/one.pdf", "/p/two.png", "/p/three.eps", "/p/one.pdf"]
    names = assign_graphic_names(uses, resolved)
    assert names == {0: "fig1.pdf", 1: "fig2a.png", 2: "fig2b.eps", 3: "fig1.pdf"}

    rewritten = rewrite_graphics(FIGURES, uses, names)
    assert "{fig2a.png}" in rewritten and "{fig1.pdf}" in rewritten
    assert "{two.png}" not in rewritten
    # The width option survives: it is the only thing holding the figure's size.
    assert "[width=0.5\\textwidth]{fig1.pdf}" in rewritten


def test_graphicspath_is_collected_and_can_be_removed():
    directories, spans = graphicspath_directories(FIGURES)
    assert directories == ["alt/"]
    assert len(spans) == 1


def test_a_graphic_without_an_extension_is_resolved_like_pdflatex(tmp_path):
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "plot.pdf").write_bytes(b"x")
    assert resolve_graphic("figures/plot", str(tmp_path)) == str(tmp_path / "figures" / "plot.pdf")
    assert resolve_graphic("figures/absent", str(tmp_path)) is None


def test_graphicspath_is_searched(tmp_path):
    (tmp_path / "alt").mkdir()
    (tmp_path / "alt" / "p.png").write_bytes(b"x")
    assert resolve_graphic("p", str(tmp_path), ["alt/"]) == str(tmp_path / "alt" / "p.png")
