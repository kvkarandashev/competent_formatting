"""The scientific-notation multiplication symbol switch.

``\\cdot`` stays the default so nothing already generated changes; AIP/JCP style wants
``\\times``, which is opt-in either globally or per formatter instance.
"""

import pytest

from competent_formatting.number_formatting import (
    LaTeXScientific,
    get_sci_mult_symbol,
    set_sci_mult_symbol,
)
from competent_formatting.tables import latex_single_number_form, latex_table

CDOT = r"\cdot"
TIMES = r"\times"


@pytest.fixture(autouse=True)
def restore_default_symbol():
    """The switch is module-level state, so put it back however the test ends."""
    previous = get_sci_mult_symbol()
    yield
    set_sci_mult_symbol(previous)


def test_default_is_cdot():
    assert get_sci_mult_symbol() == CDOT
    assert LaTeXScientific(num_numerals=2)(5.0e-2) == r"$5.00{ \cdot } 10^{-2}$"
    assert latex_single_number_form(5.0e-2) == r"5.00\cdot 10^{-2}"


def test_per_instance_override_leaves_the_default_alone():
    assert LaTeXScientific(num_numerals=2, mult_symbol=TIMES)(5.0e-2) == (
        r"$5.00{ \times } 10^{-2}$"
    )
    # The global default is untouched by an instance-level choice.
    assert LaTeXScientific(num_numerals=2)(5.0e-2) == r"$5.00{ \cdot } 10^{-2}$"


def test_global_switch_reaches_default_formatter_instances():
    set_sci_mult_symbol(TIMES)
    # Built with default args, i.e. mult_symbol=None, so it resolves at render time -- this
    # is what makes latex_table's own default formatters follow the switch.
    assert LaTeXScientific(num_numerals=2)(5.0e-2) == r"$5.00{ \times } 10^{-2}$"
    assert latex_single_number_form(5.0e-2) == r"5.00\times 10^{-2}"


def test_global_switch_reaches_latex_table():
    set_sci_mult_symbol(TIMES)
    rendered = latex_table([["x", 5.0e-2]], column_types="lc")
    assert TIMES in rendered
    assert CDOT not in rendered


def test_instance_can_override_back_to_cdot():
    set_sci_mult_symbol(TIMES)
    assert LaTeXScientific(num_numerals=2, mult_symbol=CDOT)(5.0e-2) == (
        r"$5.00{ \cdot } 10^{-2}$"
    )


def test_with_error_path_honours_the_symbol():
    set_sci_mult_symbol(TIMES)
    assert LaTeXScientific(num_numerals=2)((5.0e-2, 1.2e-3)) == (
        r"$(5.00\pm0.12){ \times } 10^{-2}$"
    )


def test_init_args_round_trips_the_kwarg():
    formatter = LaTeXScientific(num_numerals=2, mult_symbol=TIMES)
    args, kwargs = formatter._init_args()
    assert kwargs["mult_symbol"] == TIMES
    rebuilt = LaTeXScientific(*args, **kwargs)
    assert rebuilt(5.0e-2) == formatter(5.0e-2)


def test_switch_is_reversible():
    set_sci_mult_symbol(TIMES)
    set_sci_mult_symbol(CDOT)
    assert LaTeXScientific(num_numerals=2)(5.0e-2) == r"$5.00{ \cdot } 10^{-2}$"
