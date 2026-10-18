import string

from .number_formatting import (
    LaTeXInteger,
    LaTeXPlainFloat,
    LaTeXReportedFloat,
    LaTeXScientific,
    get_floatwerror_mean,
    get_sci_mult_symbol,
    is_inline_formula,
    is_reported_float,
    isfloat,
    isfloatwerr,
    isint,
    update_reported_float_alignment_kwargs,
)
from .str_formatting import LaTeX_table_newline, phantom_string

phantom = "\\phantom{\\_}"

default_column_type = "c"

cell_split = " &"

FOOTNOTE_TYPES = ("threeparttable", "multicolumn")


def alpha_footnote_marker(index):
    # 0 -> "a", 1 -> "b", ..., 25 -> "z", 26 -> "aa", 27 -> "ab", ...
    marker = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        marker = string.ascii_lowercase[remainder] + marker
    return marker


class TableFootnotes:
    """
    Collects table footnotes and hands out the markers to splice into table cells.

    `footnote_type` selects how `latex_table` renders the collected notes:
        "multicolumn"    - (default) appends the notes as full-width \\multicolumn rows inside
                           the tabular; cell markers are superscripts "$^{<marker>}$". Needs no
                           extra LaTeX package.
        "threeparttable" - wraps the tabular in a threeparttable/tablenotes block; cell
                           markers are "\\tnote{<marker>}" (needs \\usepackage{threeparttable}).
    If `check_footnote_repetition` is True, identical note texts are stored once and share
    a single marker; if False, every occurrence is kept and gets a marker of its own.
    If `sort_cell_markers` is True (default), a cell carrying several notes lists their markers
    in marker order ("$^{d,f}$") whatever order the notes were passed in; if False, the markers
    follow the order of the notes.
    """

    def __init__(
        self,
        footnote_type="multicolumn",
        check_footnote_repetition=True,
        marker_func=alpha_footnote_marker,
        sort_cell_markers=True,
    ):
        assert (
            footnote_type in FOOTNOTE_TYPES
        ), f"footnote_type must be one of {FOOTNOTE_TYPES}, got {footnote_type!r}"
        self.footnote_type = footnote_type
        self.check_footnote_repetition = check_footnote_repetition
        self.marker_func = marker_func
        self.sort_cell_markers = sort_cell_markers
        self.texts = []  # note texts in the order their markers are assigned

    def _register_index(self, text):
        if self.check_footnote_repetition and (text in self.texts):
            return self.texts.index(text)
        self.texts.append(text)
        return len(self.texts) - 1

    def cell_marker(self, notes):
        """
        Register one cell's footnote(s) and return the marker string to splice into the
        cell (e.g. "\\tnote{a}" or "$^{a,c}$"); returns "" when there are no notes.
        `notes` is a single text or a list of texts.  Their markers are listed in marker order
        when `sort_cell_markers` is set -- sorted by index, not alphabetically, so "aa" comes
        after "z" -- and a marker repeated within the cell is printed once.
        """
        if notes is None:
            return ""
        if isinstance(notes, str):
            notes = [notes]
        notes = [text for text in notes if text]
        if not notes:
            return ""
        indices = [self._register_index(text) for text in notes]
        if self.sort_cell_markers:
            indices = sorted(indices)
        # Keep the first occurrence of each marker; a deduplicated note named twice in one cell
        # would otherwise print its marker twice.
        indices = list(dict.fromkeys(indices))
        marker_str = ",".join(self.marker_func(index) for index in indices)
        if self.footnote_type == "threeparttable":
            return "\\tnote{" + marker_str + "}"
        return "$^{" + marker_str + "}$"

    def items(self):
        # (marker, text) pairs in marker-assignment order.
        return [(self.marker_func(index), text) for index, text in enumerate(self.texts)]

    def empty(self):
        return len(self.texts) == 0


class MultiColumn:
    def __init__(self, element, ncolumns=1):
        self.element = element
        self.ncolumns = ncolumns

    def closed_elements_string(self, column_type=default_column_type):
        return (
            "\\multicolumn{" + str(self.ncolumns) + "}{" + column_type + "}{" + self.element + "}"
        )

    def _init_args(self):
        return (self.element,), {"ncolumns": self.ncolumns}


class MultiRow:
    def __init__(self, element, nrows=1):
        self.element = element
        self.nrows = nrows

    def closed_elements_string(self):
        return "\\multirow{" + str(self.nrows) + "}{*}{" + self.element + "}"

    def _init_args(self):
        return (self.element,), {"nrows": self.nrows}


class NumberWithFootnote:
    """
    Wraps a numeric table cell (`float`, a `(mean, err)` tuple/`FloatWError`, `int`, or
    `ReportedFloat`) together with a footnote marker to be printed as a superscript right after
    the number, e.g. ``$(1.00\\pm0.00){ \\cdot } 10^{-2}$$^{a}$``.

    The wrapped value flows through the table's normal per-column alignment pass (so the number
    lines up with the other numbers in its column); the marker is appended afterwards. To keep
    the column's numbers centred consistently, every *other* numeric cell in the same column
    reserves the marker's width with a ``\\phantom{...}`` (driven by the ``has_footnote`` flag
    that this type sets in the column's alignment kwargs).

    `marker` is whatever `TableFootnotes.cell_marker(...)` returns (e.g. ``"$^{a}$"``), so
    footnote registration, deduplication and the note rows are reused from `TableFootnotes` --
    pass the same `TableFootnotes` instance to `latex_table` to render the note texts.

    One marker width per column is assumed (the usual case); if a column mixes markers of
    different widths, the widest is reserved for the phantom.
    """

    def __init__(self, value, marker):
        self.value = value
        self.marker = marker

    def _init_args(self):
        return (self.value, self.marker), {}


class CellStyle:
    """How a cell is set apart from the rest of its column, as LaTeX.

    Two wrappers rather than one, because a table cell is either text or an inline formula and
    the same macro does not serve both: ``\\textbf{$0.144$}`` leaves the digits unbolded and
    says nothing about it, since the math font is selected independently of the text font.
    `apply` picks the wrapper by looking at the rendered cell, so a caller passes `BOLD` and
    does not have to know which kind of cell it landed on.

    Each wrapper is a (prefix, suffix) pair, and the math one wraps the formula INCLUDING its
    dollars -- ``{\\boldmath$0.144$}`` -- because that is how a math font switch has to be
    written.
    """

    def __init__(self, text=("", ""), math=("", "")):
        self.text = tuple(text)
        self.math = tuple(math)

    def apply(self, rendered):
        prefix, suffix = self.math if is_inline_formula(rendered) else self.text
        return prefix + rendered + suffix

    def _init_args(self):
        return (), {"text": self.text, "math": self.math}


# `\boldmath` rather than `\mathbf`: it bolds the whole formula, the minus sign and the \pm
# included, and it is plain LaTeX, so a table using it needs no package the document might not
# have. `\mathbf` would leave the signs at their normal weight.
BOLD = CellStyle(text=("\\textbf{", "}"), math=("{\\boldmath", "}"))

# `\underline` is one of the few that is spelled the same in both modes.
UNDERLINE = CellStyle(text=("\\underline{", "}"), math=("\\underline{", "}"))


def cell_numeric_key(value):
    """The number a cell stands for, for comparing cells within a column.

    Every numeric cell type reduces to one float: a float-with-error to its mean, a
    `ReportedFloat` to its reported mean, and the wrappers to whatever they wrap.  A cell that
    is not a number has no key and raises, rather than being silently skipped in a comparison
    it was asked to take part in.
    """
    if isinstance(value, (Styled, NumberWithFootnote)):
        return cell_numeric_key(value.value)
    if is_reported_float(value):
        return float(value.mean)
    if isfloatwerr(value):
        return float(get_floatwerror_mean(value))
    if isfloat(value) or isint(value):
        return float(value)
    raise ValueError(f"{value!r} is not a numeric cell, so it cannot be compared with one")


class Styled:
    """Wraps any cell so that it is rendered with a `CellStyle` applied.

    The wrapped value flows through the table's normal per-column alignment pass, so a styled
    number keeps its column's padding and only then gets its wrapper.  Styling is a property of
    the finished cell, not of the number, which is why this wraps rather than replaces the value.

    `Styled` itself is unconditional -- the caller decided.  `MinInColumn` and `MaxInColumn`
    decide during that same alignment pass instead, by comparing against the other marked cells
    of their column.
    """

    def __init__(self, value, style=BOLD):
        self.value = value
        self.style = style

    def update_column_extremes(self, alignment_kwargs):
        # Nothing to accumulate: an unconditional style needs no knowledge of the column.
        return alignment_kwargs

    def shows_style(self, column_min=None, column_max=None):
        return True

    def _init_args(self):
        return (self.value,), {"style": self.style}


class ColumnExtremum(Styled):
    """Styled where the cell is the extreme value among the marked cells of its column.

    The column scope is the point, and is why these are not called "best": a table says which
    way is better by what it puts in a column, and the comparison this makes is exactly the one
    a reader makes down a column of the same quantity.  Cells that are not wrapped do not take
    part -- a column mixing an error with a count compares neither against the other -- and ties
    are all marked, because a tie is what the numbers say.

    `precision` is the number of decimals the column prints, and comparing at it is what keeps
    the mark honest: without it, two cells that both read "0.304" can come out one bold and one
    not, on a difference the table does not show.  Left at None the raw values are compared,
    which is right only where the cells are printed in full.
    """

    extremum_key = None
    extremum_function = None

    def __init__(self, value, style=BOLD, precision=None):
        super().__init__(value, style=style)
        self.precision = precision

    def key(self):
        key = cell_numeric_key(self.value)
        if self.precision is None:
            return key
        # Through the formatting rather than round(), so the comparison is on the digits the
        # cell actually prints.
        return float(f"{key:.{self.precision}f}")

    def update_column_extremes(self, alignment_kwargs):
        key = self.key()
        previous = alignment_kwargs.get(self.extremum_key)
        if previous is None:
            alignment_kwargs[self.extremum_key] = key
        else:
            alignment_kwargs[self.extremum_key] = type(self).extremum_function(previous, key)
        return alignment_kwargs

    def shows_style(self, column_min=None, column_max=None):
        extremes = {"column_min": column_min, "column_max": column_max}
        extreme = extremes[self.extremum_key]
        return extreme is not None and self.key() == extreme

    def _init_args(self):
        return (self.value,), {"style": self.style, "precision": self.precision}


class MinInColumn(ColumnExtremum):
    extremum_key = "column_min"
    extremum_function = min


class MaxInColumn(ColumnExtremum):
    extremum_key = "column_max"
    extremum_function = max


# Credit: https://tex.stackexchange.com/a/19678
def cell_wlinebreaks(lines, vertical_alignment="t", horizontal_alignment="c"):
    if len(lines) == 1:
        return lines[0]
    return (
        "\\begin{tabular}["
        + vertical_alignment
        + "]{@{}"
        + horizontal_alignment
        + "@{}}"
        + LaTeX_table_newline.join(lines)
        + "\\end{tabular}"
    )


def phantom_list(nphantoms):
    return [phantom for _ in range(nphantoms)]


def phantom_tuple(nphantoms):
    return tuple(phantom_list(nphantoms))


def preexp_power(n):
    s = "{:0.2e}".format(n)
    parts = s.split("e")
    return parts[0], int(parts[1])


def latex_single_number_form(val, phantom_minus_alignment=False, mult_symbol=None):
    pe, power = preexp_power(val)
    output = pe
    if power != 0:
        sym = mult_symbol if mult_symbol is not None else get_sci_mult_symbol()
        output += sym + " 10^{" + str(power) + "}"
    if phantom_minus_alignment and val > 0.0:
        output = "\\phantom{-}" + output
    return output


def table_transpose(table):
    # TODO if needed: make it work if MultiRow or MultiColumn are present.
    transposed_table = [[] for _ in range(len(table[0]))]
    for row in table:
        for col_id, el in enumerate(row):
            transposed_table[col_id].append(el)
    return transposed_table


def latex_table_open_element_string(
    el,
    float_formatter=LaTeXScientific(),
    int_formatter=LaTeXInteger(),
    reported_float_formatter=LaTeXReportedFloat(),
    preexp_minus=False,
    max_num_power_numerals=None,
    exp_minus=False,
    max_num_int_numerals=None,
    max_num_float_numerals=None,
    float_minus=False,
    int_minus=False,
    werrs_present=False,
    mean_decimals=0,
    err_decimals=0,
    mean_numerals=0,
    mean_minus=False,
    column_min=None,
    column_max=None,
    has_footnote=False,
    footnote_marker="",
):
    if el is None:
        return ""
    if type(el) in [MultiRow, MultiColumn]:
        return el.closed_elements_string()
    if isinstance(el, Styled):
        # Render the wrapped cell exactly as it would be rendered on its own -- the column's
        # alignment, and its footnote marker if it carries one -- and decorate the result.
        inner = latex_table_open_element_string(
            el.value,
            float_formatter=float_formatter,
            int_formatter=int_formatter,
            reported_float_formatter=reported_float_formatter,
            preexp_minus=preexp_minus,
            max_num_power_numerals=max_num_power_numerals,
            exp_minus=exp_minus,
            max_num_int_numerals=max_num_int_numerals,
            max_num_float_numerals=max_num_float_numerals,
            float_minus=float_minus,
            int_minus=int_minus,
            werrs_present=werrs_present,
            mean_decimals=mean_decimals,
            err_decimals=err_decimals,
            mean_numerals=mean_numerals,
            mean_minus=mean_minus,
            has_footnote=has_footnote,
            footnote_marker=footnote_marker,
        )
        if el.shows_style(column_min=column_min, column_max=column_max):
            return el.style.apply(inner)
        return inner
    if isinstance(el, NumberWithFootnote):
        # Render the wrapped number with the column's normal numeric alignment, then append the
        # real marker. `has_footnote=False` here: this cell carries the marker itself, so it must
        # not also reserve the alignment phantom that the column's other numbers get.
        inner = latex_table_open_element_string(
            el.value,
            float_formatter=float_formatter,
            int_formatter=int_formatter,
            reported_float_formatter=reported_float_formatter,
            preexp_minus=preexp_minus,
            max_num_power_numerals=max_num_power_numerals,
            exp_minus=exp_minus,
            max_num_int_numerals=max_num_int_numerals,
            max_num_float_numerals=max_num_float_numerals,
            float_minus=float_minus,
            int_minus=int_minus,
            werrs_present=werrs_present,
            mean_decimals=mean_decimals,
            err_decimals=err_decimals,
            mean_numerals=mean_numerals,
            mean_minus=mean_minus,
            has_footnote=False,
        )
        return inner + el.marker

    numeric = True
    if is_reported_float(el):
        s = reported_float_formatter(
            el,
            mean_decimals=mean_decimals,
            err_decimals=err_decimals,
            werrs_present=werrs_present,
            mean_numerals=mean_numerals,
            mean_minus=mean_minus,
        )
    elif isfloat(el) or isfloatwerr(el):
        if isinstance(float_formatter, LaTeXScientific):
            s = float_formatter(
                el,
                preexp_minus=preexp_minus,
                max_num_power_numerals=max_num_power_numerals,
                exp_minus=exp_minus,
                werrs_present=werrs_present,
            )
        elif isinstance(float_formatter, LaTeXPlainFloat):
            s = float_formatter(
                el,
                minus=float_minus,
                max_num_numerals=max_num_float_numerals,
                werrs_present=werrs_present,
            )
        else:
            raise Exception
    elif isint(el):
        s = int_formatter(el, minus=int_minus, max_num_numerals=max_num_int_numerals)
    else:
        numeric = False
        s = str(el)

    # A footnote in this column means one cell prints a marker superscript; reserve the same
    # width on every other numeric cell so the column's numbers stay aligned. Non-numeric cells
    # (headers, pre-formatted strings) are centred independently and left untouched.
    if has_footnote and numeric:
        s += phantom_string(footnote_marker)
    return s


def row_width(row):
    width = 0
    for el in row:
        if isinstance(el, MultiColumn):
            width += el.ncolumns
        else:
            width += 1
    return width


def update_plain_float_alignment_kwargs(
    alignment_kwargs, element, float_formatter=LaTeXPlainFloat()
):
    if element < 0:
        alignment_kwargs["float_minus"] = True

    maxnpn_key = "max_num_float_numerals"
    num_numerals = float_formatter.get_num_numerals(element)
    if (maxnpn_key not in alignment_kwargs) or (alignment_kwargs[maxnpn_key] < num_numerals):
        alignment_kwargs[maxnpn_key] = num_numerals
    return alignment_kwargs


def update_float_alignment_kwargs(alignment_kwargs, element, float_formatter=LaTeXScientific()):
    if isinstance(float_formatter, LaTeXPlainFloat):
        return update_plain_float_alignment_kwargs(
            alignment_kwargs, element, float_formatter=float_formatter
        )
    if element < 0:
        alignment_kwargs["preexp_minus"] = True
    _, exp_int = float_formatter.get_prefactor_exp_parts(element)

    num_power_numerals = len(str(exp_int))
    if exp_int < 0:
        alignment_kwargs["exp_minus"] = True
        num_power_numerals -= 1
    maxnpn_key = "max_num_power_numerals"
    if (maxnpn_key not in alignment_kwargs) or (alignment_kwargs[maxnpn_key] < num_power_numerals):
        alignment_kwargs[maxnpn_key] = num_power_numerals
    return alignment_kwargs


def update_int_alignment_kwargs(alignment_kwargs, element, int_formatter=LaTeXInteger()):
    if element < 0:
        alignment_kwargs["int_minus"] = True
    maxnpn_key = "max_num_int_numerals"
    num_numerals = int_formatter.get_num_numerals(element)
    if (maxnpn_key not in alignment_kwargs) or (alignment_kwargs[maxnpn_key] < num_numerals):
        alignment_kwargs[maxnpn_key] = num_numerals
    return alignment_kwargs


def update_alignment_kwargs(
    alignment_kwargs,
    element,
    float_formatter=LaTeXScientific(),
    int_formatter=LaTeXInteger(),
    reported_float_formatter=LaTeXReportedFloat(),
):
    if isinstance(element, Styled):
        # A conditional style decides by comparing the column's marked cells, which is the same
        # kind of per-column accumulation the numeric alignment does and happens in the same
        # pass; the wrapped value then contributes its alignment as usual.
        alignment_kwargs = element.update_column_extremes(alignment_kwargs)
        return update_alignment_kwargs(
            alignment_kwargs,
            element.value,
            float_formatter=float_formatter,
            int_formatter=int_formatter,
            reported_float_formatter=reported_float_formatter,
        )
    if isinstance(element, NumberWithFootnote):
        # Flag the column so its other numbers reserve the marker width, keep the widest marker
        # seen, and let the wrapped value contribute its usual numeric alignment via recursion.
        alignment_kwargs["has_footnote"] = True
        prev_marker = alignment_kwargs.get("footnote_marker", "")
        if len(element.marker) > len(prev_marker):
            alignment_kwargs["footnote_marker"] = element.marker
        return update_alignment_kwargs(
            alignment_kwargs,
            element.value,
            float_formatter=float_formatter,
            int_formatter=int_formatter,
            reported_float_formatter=reported_float_formatter,
        )
    if is_reported_float(element):
        return update_reported_float_alignment_kwargs(
            alignment_kwargs, element, formatter=reported_float_formatter
        )
    if isfloat(element):
        return update_float_alignment_kwargs(
            alignment_kwargs, element, float_formatter=float_formatter
        )
    if isfloatwerr(element):
        alignment_kwargs = update_float_alignment_kwargs(
            alignment_kwargs, get_floatwerror_mean(element), float_formatter=float_formatter
        )
        # Mark the column as containing floats with errors so that plain floats sharing
        # the column are rendered with a phantom error, keeping every row aligned.
        alignment_kwargs["werrs_present"] = True
        return alignment_kwargs
    if isint(element):
        return update_int_alignment_kwargs(alignment_kwargs, element, int_formatter=int_formatter)
    return alignment_kwargs


def check_keys_integer(d: dict):
    new_d = {}
    for k, v in d.items():
        new_d[int(k)] = v
    return new_d


def latex_table(
    table,
    transposed=False,
    midrule_positions=[],
    interior_rules=None,
    toprule=True,
    bottomrule=True,
    cline_positions={},
    float_formatter=LaTeXScientific(),
    int_formatter=LaTeXInteger(),
    reported_float_formatter=LaTeXReportedFloat(),
    column_types=None,
    footnotes=None,
):
    # `interior_rules` maps a row index to raw LaTeX (e.g. "\\bottomrule\n") emitted immediately
    # before that data row. Unlike `toprule`/`bottomrule` (fixed to the tabular's outer edges),
    # this allows stacking several rule-bounded sub-tables inside a single tabular -- e.g. a
    # "\\bottomrule, blank row, \\toprule" break separating two halves of one table.
    interior_rules = check_keys_integer(interior_rules) if interior_rules else {}
    # introduced after a hard-to-trace error caused by JSON packing dictionnary keys as strings
    cline_positions = check_keys_integer(cline_positions)
    # dim check
    width = row_width(table[0])
    for i in range(1, len(table)):
        assert row_width(table[i]) == width, str(table[i]) + " " + str(width)

    if transposed:
        width = len(table)
        table = table_transpose(table)
    if column_types is None:
        column_types = default_column_type * width

    # First check all arguments needed with alignment.
    alignment_kwargs_list = [{} for _ in range(width)]
    for row in table:
        col_id = 0
        for el in row:
            alignment_kwargs_list[col_id] = update_alignment_kwargs(
                alignment_kwargs_list[col_id],
                el,
                float_formatter=float_formatter,
                int_formatter=int_formatter,
                reported_float_formatter=reported_float_formatter,
            )
            if isinstance(el, MultiColumn):
                col_id += el.ncolumns
            else:
                col_id += 1

    output = "\\begin{tabular}{" + column_types + "}\n"
    if toprule:
        output += "\\toprule\n"
    for row_id, row in enumerate(table):
        if row_id in interior_rules:
            output += interior_rules[row_id]
        if row_id in midrule_positions:
            output += "\\midrule"
        if row_id in cline_positions:
            cur_cline_positions = cline_positions[row_id]
            for cline_position in cur_cline_positions:
                output += "\\cline{" + str(cline_position[0]) + "-" + str(cline_position[1]) + "}"
        col_id = 0
        for el in row:
            output += (
                " "
                + latex_table_open_element_string(
                    el,
                    float_formatter=float_formatter,
                    reported_float_formatter=reported_float_formatter,
                    **alignment_kwargs_list[col_id],
                )
                + cell_split
            )
            if isinstance(el, MultiColumn):
                col_id += el.ncolumns
            else:
                col_id += 1
        output = output[:-1] + "\\\\\n"
    if bottomrule:
        output += "\\bottomrule\n"
    # "multicolumn" footnotes live inside the tabular as full-width rows below the bottom rule.
    if (
        (footnotes is not None)
        and (footnotes.footnote_type == "multicolumn")
        and (not footnotes.empty())
    ):
        for marker, text in footnotes.items():
            output += (
                " \\multicolumn{"
                + str(width)
                + "}{l}{$^{"
                + marker
                + "}$ "
                + text
                + "}"
                + LaTeX_table_newline
                + "\n"
            )
    output += "\\end{tabular}\n"
    # "threeparttable" footnotes wrap the whole tabular in a threeparttable/tablenotes block.
    if (
        (footnotes is not None)
        and (footnotes.footnote_type == "threeparttable")
        and (not footnotes.empty())
    ):
        wrapped = "\\begin{threeparttable}\n" + output + "\\begin{tablenotes}\n"
        for marker, text in footnotes.items():
            wrapped += "\\item[" + marker + "] " + text + "\n"
        wrapped += "\\end{tablenotes}\n\\end{threeparttable}\n"
        output = wrapped
    return output
