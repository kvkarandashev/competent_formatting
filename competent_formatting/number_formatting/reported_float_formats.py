from ..str_formatting import phantom_string
from .base import LaTeXNumber, inline_formula, pm_error, pminus, pzero


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
    # A value written without a decimal point ("1" beside "0.732") needs the point's width
    # reserved too, or it comes out narrower than the column by exactly that glyph.
    point = "" if "." in num_str else phantom_string(".")
    return num_str + point + phantom_string("0") * n_pad


def integer_numerals(num_str):
    # Digits before the decimal point, sign excluded ("-9.52" -> 1, "12.3" -> 2, "7" -> 1).
    return len(num_str.lstrip("-").split(".")[0])


def phantom_pad_integer(num_str, num_numerals, minus_present=False):
    # Left-pad with phantom zeros to a common integer-part width, and with a phantom minus
    # where the column holds a negative value and this one is not it:
    #   phantom_pad_integer("0.258", 1, minus_present=True) -> "\phantom{-}0.258"
    # This is the half of the alignment that `phantom_pad_fraction` does not do.  Without it a
    # column mixing "-9.523" with "0.258" is centred cell by cell and its decimal points wander.
    padding = ""
    if minus_present and not num_str.startswith("-"):
        padding = pminus
    n_pad = num_numerals - integer_numerals(num_str)
    if n_pad > 0:
        padding = pzero * n_pad + padding
    return padding + num_str


class LaTeXReportedFloat(LaTeXNumber):
    """
    Formatter for `ReportedFloat`: keeps the reported digits verbatim and phantom-pads the
    fractional parts for column alignment. Unlike `LaTeXPlainFloat` (fixed `num_decimals`,
    rounds, left-pads to align the decimal point), this preserves precision and right-pads.

    `mean_decimals` / `err_decimals` are the per-column maxima supplied by the table's
    alignment pass; `werrs_present` marks a column that has at least one error so error-less
    values reserve the "\\pm <error>" width with a phantom.  `mean_numerals` / `mean_minus`
    are the same pass's integer-part maxima, and pad the mean on the left so that a column
    mixing "-9.523" with "0.258" still lines up on the decimal point.

    Examples (mean_decimals=2, err_decimals=2):
        ("0.92", "0.01")           -> "$0.92\\pm0.01$"
        ("0.8", "0.1")             -> "$0.8\\phantom{0}\\pm0.1\\phantom{0}$"
        ("0.7", None), werrs       -> "$0.7\\phantom{0}\\phantom{{}\\pm0.00}$"
    """

    def get_mean_decimals(self, reported_float):
        return fraction_decimals(reported_float.mean)

    def get_err_decimals(self, reported_float):
        return 0 if reported_float.err is None else fraction_decimals(reported_float.err)

    def get_mean_numerals(self, reported_float):
        return integer_numerals(reported_float.mean)

    def get_formatted_number(
        self,
        reported_float,
        mean_decimals=0,
        err_decimals=0,
        werrs_present=False,
        err_placeholder=None,
        mean_numerals=0,
        mean_minus=False,
    ):
        # Integer padding FIRST, on the reported digits, and only then the fraction padding.
        # The other order is wrong and silently so: phantom_pad_fraction gives a value written
        # without a decimal point a "\phantom{.}", and integer_numerals then splits on the "."
        # inside that macro -- integer_numerals("186\phantom{.}\phantom{0}") is 12, not 3 -- so
        # phantom_pad_integer computes a negative pad and adds nothing. A column mixing "6.15",
        # "186" and "2920" loses the left padding on every value without a point and its decimal
        # points wander, which is the failure this pair of helpers exists to prevent.
        mean_part = phantom_pad_fraction(
            phantom_pad_integer(reported_float.mean, mean_numerals, minus_present=mean_minus),
            mean_decimals,
        )
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
    # Accumulate the per-column maxima the renderer needs: widest mean fraction and integer
    # part, widest error fraction, whether any mean is negative, and whether any cell in the
    # column carries an error.
    mean_decimals = formatter.get_mean_decimals(reported_float)
    if ("mean_decimals" not in alignment_kwargs) or (
        alignment_kwargs["mean_decimals"] < mean_decimals
    ):
        alignment_kwargs["mean_decimals"] = mean_decimals
    mean_numerals = formatter.get_mean_numerals(reported_float)
    if ("mean_numerals" not in alignment_kwargs) or (
        alignment_kwargs["mean_numerals"] < mean_numerals
    ):
        alignment_kwargs["mean_numerals"] = mean_numerals
    if reported_float.mean.startswith("-"):
        alignment_kwargs["mean_minus"] = True
    if reported_float.err is not None:
        alignment_kwargs["werrs_present"] = True
        err_decimals = formatter.get_err_decimals(reported_float)
        if ("err_decimals" not in alignment_kwargs) or (
            alignment_kwargs["err_decimals"] < err_decimals
        ):
            alignment_kwargs["err_decimals"] = err_decimals
    return alignment_kwargs
