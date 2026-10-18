"""The marker string `TableFootnotes.cell_marker` hands back for a cell with several notes."""

from competent_formatting.tables import TableFootnotes


def test_markers_within_a_cell_are_sorted():
    footnotes = TableFootnotes()
    footnotes.cell_marker(["first", "second", "third", "fourth"])  # a, b, c, d
    # "sixth" is new, so it becomes "e"; "fourth" was already "d".
    assert footnotes.cell_marker(["sixth", "fourth"]) == "$^{d,e}$"


def test_sorting_can_be_switched_off():
    footnotes = TableFootnotes(sort_cell_markers=False)
    footnotes.cell_marker(["first", "second"])
    assert footnotes.cell_marker(["third", "first"]) == "$^{c,a}$"


def test_sorting_is_by_index_not_by_string():
    footnotes = TableFootnotes()
    footnotes.cell_marker([f"note {index}" for index in range(26)])  # a ... z
    # Index 26 is "aa", which sorts before "b" as a string but after "z" as a marker.
    assert footnotes.cell_marker(["new note", "note 25"]) == "$^{z,aa}$"


def test_a_repeated_note_is_marked_once():
    footnotes = TableFootnotes()
    assert footnotes.cell_marker(["same", "other", "same"]) == "$^{a,b}$"
    assert [text for _, text in footnotes.items()] == ["same", "other"]


def test_threeparttable_markers_are_sorted_too():
    footnotes = TableFootnotes(footnote_type="threeparttable")
    footnotes.cell_marker(["first", "second"])
    assert footnotes.cell_marker(["second", "first"]) == "\\tnote{a,b}"
