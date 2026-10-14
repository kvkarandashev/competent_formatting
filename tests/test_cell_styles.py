"""Marking one cell of a column, and the alignment a marked column still has to keep.

Two features that meet in the same per-column pass: `ReportedFloat`'s left padding (so a
column mixing ``-9.523`` with ``0.258`` lines up on the decimal point) and the conditional
styles, which decide whether a cell is its column's extreme while that pass is running.
"""

import pytest

from competent_formatting.number_formatting import (
    LaTeXPlainFloat,
    ReportedFloat,
    integer_numerals,
    phantom_pad_integer,
)
from competent_formatting.tables import (
    BOLD,
    UNDERLINE,
    MaxInColumn,
    MinInColumn,
    NumberWithFootnote,
    Styled,
    cell_numeric_key,
    latex_table,
)

PLAIN = LaTeXPlainFloat(num_decimals=3)


def rows_of(table_string):
    return [line for line in table_string.splitlines() if line.endswith(r"\\")]


# ----------------------------------------------------------------------------------------
# ReportedFloat: the left half of the alignment
# ----------------------------------------------------------------------------------------


def test_integer_numerals_ignores_the_sign():
    assert integer_numerals("-9.523") == 1
    assert integer_numerals("12.3") == 2
    assert integer_numerals("7") == 1


def test_phantom_pad_integer_reserves_the_minus_and_the_missing_digits():
    assert phantom_pad_integer("0.258", 1, minus_present=True) == r"\phantom{-}0.258"
    assert phantom_pad_integer("-9.523", 1, minus_present=True) == "-9.523"
    assert phantom_pad_integer("7.1", 2, minus_present=False) == r"\phantom{0}7.1"


def test_a_column_with_a_negative_value_pads_the_positive_ones():
    table = [
        ["q", "v"],
        ["MAE", ReportedFloat("0.258", "0.023")],
        ["intercept", ReportedFloat("-9.523", "0.006")],
    ]
    rendered = latex_table(table, column_types="lc", midrule_positions=[1])
    assert r"$\phantom{-}0.258\pm0.023$" in rendered
    assert r"$-9.523\pm0.006$" in rendered


def test_a_value_without_a_decimal_point_reserves_the_point():
    table = [["q", "v"], ["a", ReportedFloat("1")], ["b", ReportedFloat("0.732")]]
    rendered = latex_table(table, column_types="lc", midrule_positions=[1])
    assert r"$1\phantom{.}\phantom{0}\phantom{0}\phantom{0}$" in rendered


# ----------------------------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------------------------


def test_bold_knows_math_from_text():
    # \textbf around an inline formula leaves the digits unbolded, which is the whole reason
    # a style carries two wrappers.
    assert BOLD.apply("$0.144$") == r"{\boldmath$0.144$}"
    assert BOLD.apply("method") == r"\textbf{method}"
    assert UNDERLINE.apply("$0.144$") == r"\underline{$0.144$}"


def test_styled_is_unconditional():
    table = [["m", "v"], ["A", Styled(1.0)], ["B", 2.0]]
    rendered = latex_table(table, column_types="lc", float_formatter=PLAIN)
    assert r"{\boldmath$1.000$}" in rendered
    assert r"$2.000$" in rendered


def test_min_in_column_marks_the_smallest_and_only_that_column():
    table = [
        ["method", "MAE", "RMSE"],
        ["A", MinInColumn((0.144, 0.004)), MinInColumn((0.207, 0.017))],
        ["B", MinInColumn((0.176, 0.015)), MinInColumn((0.246, 0.026))],
    ]
    rendered = latex_table(table, column_types="lcc", midrule_positions=[1], float_formatter=PLAIN)
    assert r"{\boldmath$0.144\pm0.004$}" in rendered
    assert r"{\boldmath$0.207\pm0.017$}" in rendered
    assert r"$0.176\pm0.015$" in rendered
    assert r"{\boldmath$0.176" not in rendered


def test_a_tie_marks_every_cell_that_ties():
    table = [
        ["m", "v"],
        ["A", MinInColumn(0.144)],
        ["B", MinInColumn(0.144)],
        ["C", MinInColumn(0.2)],
    ]
    rendered = latex_table(table, column_types="lc", float_formatter=PLAIN)
    assert rendered.count(r"{\boldmath$0.144$}") == 2


def test_max_in_column_marks_the_largest():
    table = [["m", "v"], ["A", MaxInColumn(0.1)], ["B", MaxInColumn(0.9)]]
    rendered = latex_table(table, column_types="lc", float_formatter=PLAIN)
    assert r"{\boldmath$0.900$}" in rendered
    assert r"{\boldmath$0.100$}" not in rendered


def test_unmarked_cells_do_not_take_part():
    # 0.01 is the smallest number in the column but was not offered for comparison.
    table = [["m", "v"], ["A", MinInColumn(0.1)], ["B", 0.01]]
    rendered = latex_table(table, column_types="lc", float_formatter=PLAIN)
    assert r"{\boldmath$0.100$}" in rendered
    assert r"{\boldmath$0.010$}" not in rendered


def test_a_marked_cell_keeps_its_column_alignment_and_its_footnote():
    table = [
        ["m", "v"],
        ["A", MinInColumn(NumberWithFootnote(0.1, "$^{a}$"))],
        ["B", 12.0],
    ]
    rendered = latex_table(table, column_types="lc", float_formatter=PLAIN)
    # left-padded to the column's widest integer part, inside the style, marker included
    assert r"{\boldmath$\phantom{0}0.100$$^{a}$}" in rendered
    assert r"$12.000$\phantom{$^{a}$}" in rendered


def test_reported_floats_compare_by_their_reported_mean():
    assert cell_numeric_key(ReportedFloat("0.73", "0.02")) == 0.73
    assert cell_numeric_key(MinInColumn((1.5, 0.1))) == 1.5
    table = [
        ["m", "v"],
        ["A", MinInColumn(ReportedFloat("0.73"))],
        ["B", MinInColumn(ReportedFloat("1.2"))],
    ]
    rendered = latex_table(table, column_types="lc")
    assert r"{\boldmath$0.73$}" in rendered


def test_a_non_numeric_cell_cannot_be_compared():
    with pytest.raises(ValueError):
        cell_numeric_key("--")


def test_precision_compares_the_digits_the_cell_prints():
    # 0.30438 and 0.30408 both print as 0.304; at that precision they tie and both are marked.
    table = [
        ["m", "v"],
        ["A", MinInColumn(0.30438, precision=3)],
        ["B", MinInColumn(0.30408, precision=3)],
    ]
    rendered = latex_table(table, column_types="lc", float_formatter=PLAIN)
    assert rendered.count(r"{\boldmath$0.304$}") == 2
    # Without it the smaller raw value wins and the table marks a difference it does not show.
    raw = [["m", "v"], ["A", MinInColumn(0.30438)], ["B", MinInColumn(0.30408)]]
    rendered = latex_table(raw, column_types="lc", float_formatter=PLAIN)
    assert rendered.count(r"{\boldmath$0.304$}") == 1
