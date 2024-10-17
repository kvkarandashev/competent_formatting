from .number_formatting import LaTeXScientific

phantom = "\\phantom{\\_}"

default_column_alignment = "c"

cell_split = " &"


class MultiColumn:
    def __init__(self, element, ncolumns=1):
        self.element = element
        self.ncolumns = ncolumns

    def closed_elements_string(self, column_alignment=default_column_alignment):
        return (
            "\\multicolumn{"
            + str(self.ncolumns)
            + "}{"
            + column_alignment
            + "}{"
            + self.element
            + "}"
            + cell_split * (self.ncolumns - 1)
        )


class MultiRow:
    def __init__(self, element, nrows=1):
        self.element = element
        self.nrows = nrows

    def closed_elements_string(self):
        return "\\multirow{" + str(self.nrows) + "}{*}{" + self.element + "}"


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


def latex_table_open_element_string(el, float_formatter=LaTeXScientific()):
    if el is None:
        return ""
    if type(el) in [MultiRow, MultiColumn]:
        return el.closed_elements_string()
    if isinstance(el, float):
        return float_formatter(el)
    return str(el)


def row_width(row):
    width = 0
    for el in row:
        if isinstance(el, MultiColumn):
            width += el.ncolumns
        else:
            width += 1
    return width


def latex_table(
    table,
    transposed=False,
    midrule_positions=[],
    toprule=True,
    bottomrule=True,
    cline_positions={},
    float_formatter=LaTeXScientific(),
    column_definitions=None,
):
    # dim check
    width = row_width(table[0])
    for i in range(1, len(table)):
        assert row_width(table[i]) == width, str(table[i]) + " " + str(width)

    if transposed:
        width = len(table)
        table = table_transpose(table)
    if column_definitions is None:
        column_definitions = default_column_alignment * width
    output = "\\begin{tabular}{" + column_definitions + "}\n"
    if toprule:
        output += "\\toprule\n"
    for row_id, row in enumerate(table):
        if row_id in midrule_positions:
            output += "\\midrule"
        if row_id in cline_positions:
            cur_cline_positions = cline_positions[row_id]
            for cline_position in cur_cline_positions:
                output += "\\cline{" + str(cline_position[0]) + "-" + str(cline_position[1]) + "}"
        for el in row:
            output += (
                " "
                + latex_table_open_element_string(el, float_formatter=float_formatter)
                + cell_split
            )
        output = output[:-1] + "\n"
    if bottomrule:
        output += "\\bottomrule\n"
    output += "\\end{tabular}\n"
    return output
