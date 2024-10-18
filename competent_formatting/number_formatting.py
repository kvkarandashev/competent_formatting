import numpy as np

from .misc import phantom_string

pzero = phantom_string(0)
pminus = phantom_string("-")


def padded_number_string(s, minus=False, max_num_symbols=None, pad_beginning=True):
    pad_string = ""
    if minus:
        if float(s) >= 0:
            pad_string = pminus
    if max_num_symbols is not None:
        pad_string = pzero * (max_num_symbols - len(s)) + pad_string
    if len(pad_string) != 0:
        if pad_beginning:
            return pad_string + s
        else:
            return s + pad_string
    return s


def isfloat(value):
    return (type(value) in [float, np.float64]) or (
        isinstance(value, np.ndarray) and value.dtype == np.float64
    )


class LaTeXScientific:
    def __init__(self, num_numerals=1):
        self.init_format_string = "{:0." + str(num_numerals) + "e}"

    def get_prefactor_exp_parts(self, number_in):
        def_sci = self.init_format_string.format(number_in)
        parts = def_sci.split("e")
        return parts[0], int(parts[1])

    def __call__(
        self, number_in, preexp_minus=False, max_num_power_numerals=None, exp_minus=False
    ):
        prefactor, exp_int = self.get_prefactor_exp_parts(number_in)

        no_exp_needed = exp_int == 0

        output = padded_number_string(prefactor, minus=preexp_minus)

        if not (no_exp_needed and (max_num_power_numerals is None)):
            exp_part = (
                "{ \\cdot } 10^{"
                + padded_number_string(
                    str(exp_int),
                    minus=exp_minus,
                    max_num_symbols=max_num_power_numerals,
                    pad_beginning=False,
                )
                + "}"
            )
            if no_exp_needed:
                exp_part = phantom_string(exp_part)
            output += exp_part
        return r"$" + output + "$"


class LaTeXPlainFloat:
    def __init__(self, num_decimals=1):
        self.init_format_string = "{:0." + str(num_decimals) + "f}"

    def get_num_numerals(self, number_in):
        return len(self.init_format_string.format(number_in))

    def __call__(self, number_in, minus=False, max_num_numerals=None):
        s = self.init_format_string.format(number_in)
        return r"$" + padded_number_string(s, minus=minus, max_num_symbols=max_num_numerals) + "$"


def isint(value):
    return (type(value) in [int, np.int64]) or (
        isinstance(value, np.ndarray) and value.dtype == np.int64
    )


class LaTeXInteger:
    def __init__(self):
        pass

    def get_num_numerals(self, number_in):
        return len(str(number_in))

    def __call__(self, number_in, minus=False, max_num_numerals=None):
        return (
            r"$"
            + padded_number_string(str(number_in), minus=minus, max_num_symbols=max_num_numerals)
            + "$"
        )
