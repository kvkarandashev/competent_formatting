# K.Karan.: I am still not %100 decided whether using error_roundup is a good idea.

from .utils import (
    FloatWError,
    brackets_enclosure,
    error_roundup,
    inline_formula,
    isfloatwerr,
    padded_number_string,
    phantom_string,
    pm_error,
    pminus,
    shift_decimal,
)


class LaTeXNumber:
    def __init__(self, *args, **kwargs):
        pass

    def get_formatted_number(self, number_in, **kwargs):
        pass

    def __call__(self, number_in, **kwargs):
        if isinstance(number_in, str):
            return number_in
        return self.get_formatted_number(number_in, **kwargs)


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

        final_exp = max(exp_init, exp_error)
        prefactor = shift_decimal(prefactor, exp_init - final_exp)
        error_prefactor = shift_decimal(error_prefactor, exp_error - final_exp)

        if number_in.mean_val < 0:
            bracket_kwargs = {"outside_left": 1}
        else:
            bracket_kwargs = {}

        exp_needed = final_exp == 0
        output = pm_error(prefactor, error_prefactor)
        output = brackets_enclosure(output, phantom=(not exp_needed), **bracket_kwargs)
        if preexp_minus and (number_in.mean_val > 0):
            output = pminus + output
        output += self.get_exp_part(
            final_exp, max_num_power_numerals=max_num_power_numerals, exp_minus=exp_minus
        )
        return output

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
        self.init_format_string = "{:0." + str(num_decimals) + "f}"

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


class LaTeXInteger(LaTeXNumber):
    def get_num_numerals(self, number_in):
        return len(str(number_in))

    def get_formatted_number(self, number_in, minus=False, max_num_numerals=None):
        return inline_formula(
            padded_number_string(str(number_in), minus=minus, max_num_symbols=max_num_numerals)
        )
