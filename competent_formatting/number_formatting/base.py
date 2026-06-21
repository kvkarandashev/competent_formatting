from ..str_formatting import phantom_string

pzero = phantom_string(0)
pminus = phantom_string("-")


def padded_number_string(s, minus=False, max_num_symbols=None, pad_beginning=True):
    pad_string = ""
    if minus:
        if s[0] != "-":
            pad_string = pminus
    if max_num_symbols is not None:
        pad_string = pzero * (max_num_symbols - len(s)) + pad_string
    if len(pad_string) != 0:
        if pad_beginning:
            return pad_string + s
        else:
            return s + pad_string
    return s


def inline_formula(s):
    return "$" + s + "$"


def pm_error(s1, s2):
    return s1 + "\\pm" + s2


class LaTeXNumber:
    def __init__(self, *args, **kwargs):
        pass

    def get_formatted_number(self, number_in, **kwargs):
        pass

    def __call__(self, number_in, **kwargs):
        if isinstance(number_in, str):
            return number_in
        return self.get_formatted_number(number_in, **kwargs)

    def _init_args(self):
        return (), {}
