import numpy as np


def isfloat(value):
    return (type(value) in [float, np.float64]) or (
        isinstance(value, np.ndarray) and value.dtype == np.float64
    )


def isint(value):
    return (type(value) in [int, np.int64]) or (
        isinstance(value, np.ndarray) and value.dtype == np.int64
    )


def int_numeral_length(i):
    return len(str(i))
