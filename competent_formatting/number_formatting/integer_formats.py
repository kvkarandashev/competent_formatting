from .base import LaTeXNumber, inline_formula, padded_number_string


class LaTeXInteger(LaTeXNumber):
    def get_num_numerals(self, number_in):
        return len(str(number_in))

    def get_formatted_number(self, number_in, minus=False, max_num_numerals=None):
        return inline_formula(
            padded_number_string(str(number_in), minus=minus, max_num_symbols=max_num_numerals)
        )
