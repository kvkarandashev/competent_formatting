from ..str_formatting import phantom_string
from .base import LaTeXNumber, inline_formula, pm_error


class ReportedFloat:
    """
    A measured value whose digits are preserved exactly as reported (kept as strings, never
    rounded), so a table can phantom-align the fractional parts. Put `ReportedFloat` objects
    in `latex_table` cells: the per-column alignment pass renders them via `LaTeXReportedFloat`,
    exactly the way numeric floats flow through their formatter.
    """

    def __init__(self, mean, err=None):
        self.mean = str(mean)
        self.err = None if err is None else str(err)

    def _init_args(self):
        return (self.mean,), {"err": self.err}


def is_reported_float(value):
    return isinstance(value, ReportedFloat)


def fraction_decimals(num_str):
    # Number of digits after the decimal point in a numeric string ("0.620" -> 3, "5" -> 0).
    return len(num_str.split(".")[1]) if "." in num_str else 0


def phantom_pad_fraction(num_str, num_decimals):
    # Right-pad the fractional part with phantom zeros up to `num_decimals` digits so a column
    # lines up on the decimal point WITHOUT changing the reported digits:
    #   phantom_pad_fraction("0.9", 3) -> "0.9\phantom{0}\phantom{0}".
    # Unlike LaTeXPlainFloat (fixed `num_decimals`, rounds), this keeps the value verbatim.
    n_pad = num_decimals - fraction_decimals(num_str)
    if n_pad <= 0:
        return num_str
    return num_str + phantom_string("0") * n_pad


class LaTeXReportedFloat(LaTeXNumber):
    """
    Formatter for `ReportedFloat`: keeps the reported digits verbatim and phantom-pads the
    fractional parts for column alignment. Unlike `LaTeXPlainFloat` (fixed `num_decimals`,
    rounds, left-pads to align the decimal point), this preserves precision and right-pads.

    `mean_decimals` / `err_decimals` are the per-column maxima supplied by the table's
    alignment pass; `werrs_present` marks a column that has at least one error so error-less
    values reserve the "\\pm <error>" width with a phantom.

    Examples (mean_decimals=2, err_decimals=2):
        ("0.92", "0.01")           -> "$0.92\\pm0.01$"
        ("0.8", "0.1")             -> "$0.8\\phantom{0}\\pm0.1\\phantom{0}$"
        ("0.7", None), werrs       -> "$0.7\\phantom{0}\\phantom{{}\\pm0.00}$"
    """

    def get_mean_decimals(self, reported_float):
        return fraction_decimals(reported_float.mean)

    def get_err_decimals(self, reported_float):
        return 0 if reported_float.err is None else fraction_decimals(reported_float.err)

    def get_formatted_number(
        self,
        reported_float,
        mean_decimals=0,
        err_decimals=0,
        werrs_present=False,
        err_placeholder=None,
    ):
        mean_part = phantom_pad_fraction(reported_float.mean, mean_decimals)
        if reported_float.err is not None:
            return inline_formula(
                pm_error(mean_part, phantom_pad_fraction(reported_float.err, err_decimals))
            )
        if not werrs_present:
            # The whole column is error-free; there is no "\pm error" width to reserve.
            return inline_formula(mean_part)
        if err_placeholder is None:
            err_placeholder = "0." + "0" * err_decimals if err_decimals > 0 else "0"
        # The leading "{}" keeps \pm a binary operator so the phantom reserves the same width
        # (incl. spacing) as a real "\pm error"; cf. LaTeXPlainFloat.get_formatted_float_werrs.
        return inline_formula(mean_part + phantom_string(pm_error("{}", err_placeholder)))


default_reported_float_formatter = LaTeXReportedFloat()


def update_reported_float_alignment_kwargs(
    alignment_kwargs, reported_float, formatter=default_reported_float_formatter
):
    # Accumulate the per-column maxima the renderer needs: widest mean fraction, widest error
    # fraction, and whether any cell in the column carries an error.
    mean_decimals = formatter.get_mean_decimals(reported_float)
    if ("mean_decimals" not in alignment_kwargs) or (
        alignment_kwargs["mean_decimals"] < mean_decimals
    ):
        alignment_kwargs["mean_decimals"] = mean_decimals
    if reported_float.err is not None:
        alignment_kwargs["werrs_present"] = True
        err_decimals = formatter.get_err_decimals(reported_float)
        if ("err_decimals" not in alignment_kwargs) or (
            alignment_kwargs["err_decimals"] < err_decimals
        ):
            alignment_kwargs["err_decimals"] = err_decimals
    return alignment_kwargs
