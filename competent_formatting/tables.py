from .number_formatting import LaTeXInteger, LaTeXPlainFloat, LaTeXScientific, isfloat, isint

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


def latex_table_open_element_string(
    el,
    float_formatter=LaTeXScientific(),
    int_formatter=LaTeXInteger(),
    preexp_minus=False,
    max_num_power_numerals=None,
    exp_minus=False,
    max_num_int_numerals=None,
    max_num_float_numerals=None,
    float_minus=False,
    int_minus=False,
):
    if el is None:
        return ""
    if type(el) in [MultiRow, MultiColumn]:
        return el.closed_elements_string()
    if isfloat(el):
        if isinstance(float_formatter, LaTeXScientific):
            return float_formatter(
                el,
                preexp_minus=preexp_minus,
                max_num_power_numerals=max_num_power_numerals,
                exp_minus=exp_minus,
            )
        elif isinstance(float_formatter, LaTeXPlainFloat):
            return float_formatter(el, minus=float_minus, max_num_numerals=max_num_float_numerals)
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
    alignment_kwargs, element, float_formatter=LaTeXScientific(), int_formatter=LaTeXInteger()
):
    if isfloat(element):
        return update_float_alignment_kwargs(
            alignment_kwargs, element, float_formatter=float_formatter
        )
    if isint(element):
        return update_int_alignment_kwargs(alignment_kwargs, element, int_formatter=int_formatter)
    return alignment_kwargs


def latex_table(
    table,
    transposed=False,
    midrule_positions=[],
    toprule=True,
    bottomrule=True,
    cline_positions={},
    float_formatter=LaTeXScientific(),
    int_formatter=LaTeXInteger(),
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
            )
            if isinstance(el, MultiColumn):
                col_id += el.ncolumns
            else:
                col_id += 1

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
        col_id = 0
        for el in row:
            output += (
                " "
                + latex_table_open_element_string(
                    el, float_formatter=float_formatter, **alignment_kwargs_list[col_id]
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
    output += "\\end{tabular}\n"
    return output
