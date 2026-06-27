# K.Karan.: I am still not %100 decided whether using error_roundup is a good idea.

from ..str_formatting import phantom_string
from .base import LaTeXNumber, inline_formula, padded_number_string, pm_error, pminus


class FloatWError:
    def __init__(self, mean_val, stat_err=None):
        self.mean_val = mean_val
        self.stat_err = stat_err
        if stat_err is not None:
            # A zero error is a legitimate value (e.g. measurements that coincide exactly);
            # `None` is the sentinel for "no error", so only forbid genuinely negative errors.
            assert stat_err >= 0


def isfloatwerr(value):
    return isinstance(value, tuple) or isinstance(value, list) or isinstance(value, FloatWError)


def get_floatwerror_mean(value):
    if isinstance(value, tuple) or isinstance(value, list):
        return value[0]
    assert isinstance(value, FloatWError)
    return value.mean_val


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


def brackets_enclosure(s, phantom=False, outside_left=0):
    start_symbols = s[:outside_left]
    inside_symbols = s[outside_left:]
    if phantom:
        bracketed = phantom_string("(") + inside_symbols + phantom_string(")")
    else:
        bracketed = f"({inside_symbols})"
    return start_symbols + bracketed


class LaTeXFloat(LaTeXNumber):
    def get_formatted_float(self, number_in, **kwargs):
        pass

    def get_formatted_float_werrs(self, number_in, **kwargs):
        pass

    def get_formatted_number(self, number_in, werrs_present=False, **kwargs):
        if isfloatwerr(number_in):
            number_in = FloatWError(mean_val=number_in[0], stat_err=number_in[1])
        elif werrs_present and (not isinstance(number_in, FloatWError)):
            number_in = FloatWError(mean_val=number_in, stat_err=None)
        if werrs_present or isinstance(number_in, FloatWError):
            return self.get_formatted_float_werrs(number_in, **kwargs)
        return self.get_formatted_float(number_in, **kwargs)


class LaTeXScientific(LaTeXFloat):
    def __init__(self, num_numerals=1, error_roundup=False):
        self.num_numerals = num_numerals
        self.error_roundup = error_roundup

    def _init_args(self):
        return (), {"num_numerals": self.num_numerals, "error_roundup": self.error_roundup}

    def get_prefactor_exp_parts(self, number_in, num_numerals=None):
        if num_numerals is None:
            num_numerals = self.num_numerals
        def_sci = ("{:0." + str(num_numerals) + "e}").format(number_in)
        parts = def_sci.split("e")
        return parts[0], int(parts[1])

    def get_exp_part(self, exp_int, max_num_power_numerals=None, exp_minus=False):
        no_exp_needed = exp_int == 0
        if no_exp_needed and (max_num_power_numerals is None):
            return ""
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
        if exp_int == 0:
            exp_part = phantom_string(exp_part)
        return exp_part

    def get_formatted_float_werrs(
        self,
        number_in: FloatWError,
        preexp_minus=False,
        max_num_power_numerals=None,
        exp_minus=False,
    ):
        prefactor, exp_init = self.get_prefactor_exp_parts(number_in.mean_val)
        if number_in.stat_err is None:
            # No error to show, but the column contains floats-with-errors: render the mean
            # as usual and hide a same-width "\pm error" placeholder behind a phantom so the
            # row stays aligned with the floats-with-errors in the same column.
            final_exp = exp_init
            final_prefactor_format = "{:0." + str(self.num_numerals) + "f}"
            prefactor = final_prefactor_format.format(float(prefactor))
            error_placeholder = final_prefactor_format.format(0.0)
            if number_in.mean_val < 0:
                bracket_kwargs = {"outside_left": 1}
            else:
                bracket_kwargs = {}
            exp_needed = final_exp != 0
            # The leading "{}" is a zero-width ordinary atom that keeps \pm classified as a
            # binary operator inside the \phantom, so the placeholder reserves the same
            # \medmuskip spacing (hence the same width) as a real "\pm error".
            output = prefactor + phantom_string(pm_error("{}", error_placeholder))
            output = brackets_enclosure(output, phantom=(not exp_needed), **bracket_kwargs)
            if preexp_minus and (number_in.mean_val > 0):
                output = pminus + output
            output += self.get_exp_part(
                final_exp, max_num_power_numerals=max_num_power_numerals, exp_minus=exp_minus
            )
            return inline_formula(output)
        err_num_numerals = self.num_numerals
        if self.error_roundup:
            err_num_numerals += 1
        error_prefactor, exp_error = self.get_prefactor_exp_parts(
            number_in.stat_err, num_numerals=err_num_numerals
        )
        if self.error_roundup:
            error_prefactor = error_roundup(error_prefactor)
            # decimal point was moved as a result of rounding up
            if error_prefactor[1] != ".":
                error_prefactor = shift_decimal(error_prefactor, -1)
                exp_error += 1

        # A value of exactly 0 has no meaningful exponent ("{:e}".format(0.0) reports 0), so it
        # must not drag the shared exponent down: a small mean like 0.01 paired with a 0.0 error
        # would otherwise pick final_exp=0 and collapse into a plain "0.01" instead of
        # "1.00 \cdot 10^{-2}". Choose the common exponent from whichever component is nonzero.
        candidate_exps = []
        if number_in.mean_val != 0:
            candidate_exps.append(exp_init)
        if number_in.stat_err != 0:
            candidate_exps.append(exp_error)
        final_exp = max(candidate_exps) if candidate_exps else 0
        prefactor = shift_decimal(prefactor, exp_init - final_exp)
        error_prefactor = shift_decimal(error_prefactor, exp_error - final_exp)

        final_prefactor_format = "{:0." + str(self.num_numerals) + "f}"
        prefactor = final_prefactor_format.format(float(prefactor))
        error_prefactor = final_prefactor_format.format(float(error_prefactor))

        if number_in.mean_val < 0:
            bracket_kwargs = {"outside_left": 1}
        else:
            bracket_kwargs = {}

        exp_needed = final_exp != 0
        output = pm_error(prefactor, error_prefactor)
        output = brackets_enclosure(output, phantom=(not exp_needed), **bracket_kwargs)
        if preexp_minus and (number_in.mean_val > 0):
            output = pminus + output
        output += self.get_exp_part(
            final_exp, max_num_power_numerals=max_num_power_numerals, exp_minus=exp_minus
        )
        return inline_formula(output)

    def get_formatted_float(
        self, number_in, preexp_minus=False, max_num_power_numerals=None, exp_minus=False
    ):
        prefactor, exp_int = self.get_prefactor_exp_parts(number_in)

        output = padded_number_string(prefactor, minus=preexp_minus)

        output += self.get_exp_part(
            exp_int, max_num_power_numerals=max_num_power_numerals, exp_minus=exp_minus
        )

        return inline_formula(output)


class LaTeXPlainFloat(LaTeXFloat):
    def __init__(self, num_decimals=1):
        self.num_decimals = num_decimals
        self.init_format_string = "{:0." + str(self.num_decimals) + "f}"

    def _init_args(self):
        return (), {"num_decimals": self.num_decimals}

    def get_num_numerals(self, number_in):
        return len(self.init_format_string.format(number_in))

    def get_formatted_float_werrs(
        self, number_in: FloatWError, minus=False, max_num_numerals=None
    ):
        mean_str = self.get_formatted_float(
            number_in.mean_val,
            minus=minus,
            max_num_numerals=max_num_numerals,
            return_inline_formula=False,
        )
        if number_in.stat_err is None:
            # The value has no error, but it shares a column with floats that do. Reserve
            # the exact horizontal space of the "\pm error" part with a phantom so the mean
            # stays aligned with the floats-with-errors in the same column.
            err_placeholder = self.get_formatted_float(
                0.0,
                minus=minus,
                max_num_numerals=max_num_numerals,
                return_inline_formula=False,
            )
            # The leading "{}" is a zero-width ordinary atom that keeps \pm classified as a
            # binary operator inside the \phantom, so the placeholder reserves the same
            # \medmuskip spacing (hence the same width) as a real "\pm error".
            return inline_formula(mean_str + phantom_string(pm_error("{}", err_placeholder)))
        err_str = self.get_formatted_float(
            number_in.stat_err,
            minus=minus,
            max_num_numerals=max_num_numerals,
            return_inline_formula=False,
        )
        s = pm_error(mean_str, err_str)
        return inline_formula(s)

    def get_formatted_float(
        self, number_in, minus=False, max_num_numerals=None, return_inline_formula=True
    ):
        s = self.init_format_string.format(number_in)
        s = padded_number_string(s, minus=minus, max_num_symbols=max_num_numerals)
        if return_inline_formula:
            s = inline_formula(s)
        return s
