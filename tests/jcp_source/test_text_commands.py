"""``cf_flatten`` and ``cf_macro_removal``: the text-only commands. No TeX needed."""

from click.testing import CliRunner

from competent_formatting.bin.flatten import main as cf_flatten
from competent_formatting.bin.macro_removal import main as cf_macro_removal
from competent_formatting.processing.macro_removal import leftover_markup


def write(directory, name, text):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_flatten_inlines_and_keeps_comments_unless_asked(tmp_path):
    write(tmp_path, "parts/a.tex", "inside % note\n")
    main = write(tmp_path, "main.tex", "\\externaldocument{x}\n\\input{parts/a}\nend\n")
    kept = CliRunner().invoke(cf_flatten, [str(main)])
    assert kept.exit_code == 0
    assert kept.output == "\\externaldocument{x}\ninside % note\n\\space\nend\n"
    stripped = CliRunner().invoke(cf_flatten, [str(main), "--strip_comments"])
    assert "note" not in stripped.output


def test_flatten_strips_markup_and_writes_a_file(tmp_path):
    main = write(tmp_path, "main.tex", "a \\rev{b} \\begin{revblock}c\\end{revblock}\n")
    out = tmp_path / "flat.tex"
    result = CliRunner().invoke(
        cf_flatten,
        [str(main), "-o", str(out), "--opened_macro", "rev", "--opened_env", "revblock"],
    )
    assert result.exit_code == 0
    assert out.read_text() == "a b c\n"


def test_flatten_reports_a_missing_input(tmp_path):
    main = write(tmp_path, "main.tex", "\\input{nowhere}\n")
    result = CliRunner().invoke(cf_flatten, [str(main)])
    assert result.exit_code == 1
    assert "nowhere" in result.output


def test_macro_removal_takes_both_option_forms(tmp_path):
    main = write(tmp_path, "main.tex", "\\rev{a} \\add{b} \\note{c}\n")
    result = CliRunner().invoke(
        cf_macro_removal,
        [str(main), "--opened_fields", "rev:add", "--removed_macro", "note"],
    )
    assert result.exit_code == 0
    assert result.output == "a b \n"


def test_macro_removal_fails_on_markup_it_cannot_open(tmp_path):
    # \rev with nothing after it to open.
    main = write(tmp_path, "main.tex", "\\let\\old\\rev\n")
    result = CliRunner().invoke(cf_macro_removal, [str(main), "--opened_macro", "rev"])
    assert result.exit_code == 1
    assert "unbalanced" in result.output


def test_leftovers_are_found_in_code_but_not_in_comments():
    assert leftover_markup("\\revx \\rev % \\begin{revblock}\n", {"rev"}, {"revblock"}) == [
        "\\rev"
    ]
