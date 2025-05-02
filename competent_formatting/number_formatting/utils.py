import numpy as np

from ..str_formatting import phantom_string

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


def int_numeral_length(i):
    return len(str(i))


def insert_decimal(str_in, pos):
    return str_in[:pos] + "." + str_in[pos:]


def str_add1(i):
    return str(int(i) + 1)


def error_roundup(fraction_str_in, max_numeral_num):
    """
    Roundup `fraction_str_in` to just one numeral (or two if the first numeral is 1), the roundup is done to the larger numeral.

    K.Karan: Based on a procedure I cannot find online anymore, perhaps should not be used.
    """
    s = fraction_str_in[0]
    if s == "9":
        return "10"
    if (s != "0") and (s != "1"):
        return str(int(s) + 1)

    str_no_decim = "".join(fraction_str_in.split("."))

    prefinal_no_decim = None
    for i in range(max_numeral_num):
        s = str_no_decim[i]
        if s == "0":
            continue
        if s == "1":
            if i == max_numeral_num - 1:
                prefinal_no_decim = fraction_str_in[: max_numeral_num - 1] + "2"
                break
            last_symbol = fraction_str_in[i + 1]
            if last_symbol == "9":
                prefinal_no_decim = fraction_str_in[: i - 1] + "2"
            else:
                prefinal_no_decim = fraction_str_in[: i + 1] + str_add1(last_symbol)
            break
        last_symbol = fraction_str_in[i]
        if last_symbol == "9":
            prefinal_no_decim = fraction_str_in[: i - 1] + "1"
        else:
            prefinal_no_decim = fraction_str_in[:i] + str_add1(last_symbol)
        break

    if prefinal_no_decim is None:
        prefinal_no_decim = fraction_str_in[:max_numeral_num]
        next_s = fraction_str_in[max_numeral_num]
        if next_s == "0" or next_s == "1":
            last_symbol = "0"
        else:
            last_symbol = "1"
        prefinal_no_decim = prefinal_no_decim[:-1] + last_symbol

    return insert_decimal(prefinal_no_decim, 1)


def shift_decimal(str_rep_in, shift_num):
    if shift_num == 0:
        return str_rep_in
    str_spl = str_rep_in.split(".")
    assert len(str_spl) == 2
    prefac_part, frac_part = str_spl
    if shift_num > 0:
        num_transferred_numerals = min(len(frac_part), shift_num)
        prefac_part += frac_part[:num_transferred_numerals]
        frac_part = frac_part[num_transferred_numerals:]
        if num_transferred_numerals != shift_num:
            prefac_part += "0" * (shift_num - num_transferred_numerals)
        if len(frac_part) == 0:
            return prefac_part
    else:
        num_transferred_numerals = min(len(prefac_part), -shift_num)
        frac_part = prefac_part[-num_transferred_numerals:] + frac_part
        prefac_part = prefac_part[:-num_transferred_numerals]
        if len(prefac_part) == 0:
            prefac_part = "0"
        if num_transferred_numerals != -shift_num:
            frac_part = "0" * (-shift_num - num_transferred_numerals) + frac_part
    return ".".join([prefac_part, frac_part])


def isint(value):
    return (type(value) in [int, np.int64]) or (
        isinstance(value, np.ndarray) and value.dtype == np.int64
    )


def inline_formula(s):
    return "$" + s + "$"


def pm_error(s1, s2):
    return s1 + "\\pm" + s2


def brackets_enclosure(s, phantom=False, outside_left=0):
    start_symbols = s[:outside_left]
    inside_symbols = s[outside_left:]
    if phantom:
        bracketed = phantom_string("(") + inside_symbols + phantom_string(")")
    else:
        bracketed = f"({inside_symbols})"
    return start_symbols + bracketed


class FloatWError:
    def __init__(self, mean_val, stat_err=None):
        self.mean_val = mean_val
        self.stat_err = stat_err
        if stat_err is not None:
            assert stat_err > 0


def isfloatwerr(value):
    return isinstance(value, tuple) or isinstance(value, list) or isinstance(value, FloatWError)


def get_floatwerror_mean(value):
    if isinstance(value, tuple) or isinstance(value, list):
        return value[0]
    assert isinstance(value, FloatWError)
    return value.mean_val
