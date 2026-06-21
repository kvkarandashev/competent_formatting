import string

from .number_formatting import (
    LaTeXInteger,
    LaTeXPlainFloat,
    LaTeXReportedFloat,
    LaTeXScientific,
    get_floatwerror_mean,
    is_reported_float,
    isfloat,
    isfloatwerr,
    isint,
    update_reported_float_alignment_kwargs,
)
from .str_formatting import LaTeX_table_newline

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
    """

    def __init__(
        self,
        footnote_type="multicolumn",
        check_footnote_repetition=True,
        marker_func=alpha_footnote_marker,
    ):
        assert (
            footnote_type in FOOTNOTE_TYPES
        ), f"footnote_type must be one of {FOOTNOTE_TYPES}, got {footnote_type!r}"
        self.footnote_type = footnote_type
        self.check_footnote_repetition = check_footnote_repetition
        self.marker_func = marker_func
        self.texts = []  # note texts in the order their markers are assigned

    def _register(self, text):
        if self.check_footnote_repetition and (text in self.texts):
            index = self.texts.index(text)
        else:
            index = len(self.texts)
            self.texts.append(text)
        return self.marker_func(index)

    def cell_marker(self, notes):
        """
        Register one cell's footnote(s) and return the marker string to splice into the
        cell (e.g. "\\tnote{a}" or "$^{a,c}$"); returns "" when there are no notes.
        `notes` is a single text or a list of texts, kept in the given order.
        """
        if notes is None:
            return ""
        if isinstance(notes, str):
            notes = [notes]
        notes = [text for text in notes if text]
        if not notes:
            return ""
        marker_str = ",".join(self._register(text) for text in notes)
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


def latex_single_number_form(val, phantom_minus_alignment=False):
    pe, power = preexp_power(val)
    output = pe
    if power != 0:
        output += "\\cdot 10^{" + str(power) + "}"
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
):
    if el is None:
        return ""
    if type(el) in [MultiRow, MultiColumn]:
        return el.closed_elements_string()
    if is_reported_float(el):
        return reported_float_formatter(
            el, mean_decimals=mean_decimals, err_decimals=err_decimals, werrs_present=werrs_present
        )
    if isfloat(el) or isfloatwerr(el):
        if isinstance(float_formatter, LaTeXScientific):
            return float_formatter(
                el,
                preexp_minus=preexp_minus,
                max_num_power_numerals=max_num_power_numerals,
                exp_minus=exp_minus,
                werrs_present=werrs_present,
            )
        elif isinstance(float_formatter, LaTeXPlainFloat):
            return float_formatter(
                el,
                minus=float_minus,
                max_num_numerals=max_num_float_numerals,
                werrs_present=werrs_present,
            )
        raise Exception
    if isint(el):
        return int_formatter(el, minus=int_minus, max_num_numerals=max_num_int_numerals)
    return str(el)


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
    toprule=True,
    bottomrule=True,
    cline_positions={},
    float_formatter=LaTeXScientific(),
    int_formatter=LaTeXInteger(),
    reported_float_formatter=LaTeXReportedFloat(),
    column_types=None,
    footnotes=None,
):
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
