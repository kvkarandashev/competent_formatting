"""
Introduced since it's better to maintain test benchmarks in *.json rather than *.pkl format.
"""
import json

from .number_formatting import FloatWError, LaTeXInteger, LaTeXPlainFloat, LaTeXScientific
from .tables import MultiColumn, MultiRow

internal_name_dict = {
    LaTeXScientific: "__LaTeXScientific__",
    LaTeXInteger: "__LaTeXInteger__",
    LaTeXPlainFloat: "__LaTeXPlainFloat__",
    FloatWError: "__FloatWError__",
    MultiRow: "__MultiRow__",
    MultiColumn: "__MultiColumn__",
}

internal_class_dict = {}
for k, v in internal_name_dict.items():
    internal_class_dict[v] = k


def represents_internal_object(d):
    if not isinstance(d, dict):
        return False
    ks = list(d.keys())
    if len(ks) != 1:
        return False
    return ks[0] in internal_class_dict


class ALFEncoder(json.JSONEncoder):
    def default(self, obj):
        tobj = type(obj)
        if tobj not in internal_name_dict:
            return super().default(obj)
        return {internal_name_dict[tobj]: obj._init_args()}


class ALFDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, object_hook=self.object_hook, **kwargs)

    def object_hook(self, d):
        if not represents_internal_object(d):
            return d

        cls = internal_class_dict[list(d.keys())[0]]
        val = list(d.values())[0]
        return cls(*val[0], **val[1])
