"""Resolve ``\\externaldocument`` into labels the document defines itself.

``xr``/``xr-hyper`` let one document ``\\ref`` another's labels by reading the other's
``.aux`` at compile time: ``\\externaldocument[M-]{main}`` turns every ``\\newlabel{x}`` in
``main.aux`` into ``\\newlabel{M-x}``. That is exactly what breaks once the documents are
compiled somewhere else -- arXiv builds each top-level file on its own and concatenates the
PDFs, and an ``.aux`` is not something to ship.

So the packager does what ``xr`` would have done, ahead of time: the ``\\externaldocument`` call
is replaced by the prefixed ``\\newlabel`` lines themselves, taken from the ``.aux`` of the
*cleaned* build of the referenced document (the numbers the reader will see in its PDF).
Every way of reaching a label keeps working -- ``\\ref``, ``\\eqref``, ``\\pageref`` and any
author macro built on them -- because nothing at the call sites is rewritten.

The hyperref anchor of each label is blanked. It names a destination inside the *other* PDF;
left in place it would silently link to whatever this document has under the same anchor name
(``section.3`` exists in both). With it blank, hyperref prints the number without a link.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from .latex_spans import code_spans, skip_balanced_group

_EXTERNALDOCUMENT = re.compile(r"\\externaldocument(?![a-zA-Z@])")
_NEWLABEL = "\\newlabel{"
HYPERREF_ANCHOR_FIELD = 3  # {number}{page}{title}{anchor}{extra}


@dataclass
class ExternalDocument:
    start: int
    end: int
    prefix: str
    name: str
    url: Optional[str] = None


def _skip_space(text, position):
    while position < len(text) and text[position] in " \t\n":
        position += 1
    return position


def _optional_argument(text, position):
    """``(value, end)`` of a ``[...]`` at ``position`` (after spaces), or ``(None, position)``."""
    start = _skip_space(text, position)
    if start < len(text) and text[start] == "[":
        closing = text.find("]", start)
        if closing != -1:
            return text[start + 1 : closing], closing + 1
    return None, position


def find_external_documents(text):
    """Every ``\\externaldocument[prefix]{name}[url]`` in live code, in order."""
    found = []
    for span in code_spans(text):
        for match in _EXTERNALDOCUMENT.finditer(text, span.start, span.end):
            prefix, position = _optional_argument(text, match.end())
            position = _skip_space(text, position)
            if position >= len(text) or text[position] != "{":
                continue
            end = skip_balanced_group(text, position)
            name = text[position + 1 : end - 1].strip()
            url, end = _optional_argument(text, end)  # xr-hyper's trailing [url]
            found.append(ExternalDocument(match.start(), end, prefix or "", name, url))
    return found


def _groups(text, position):
    """Consecutive ``{...}`` groups from ``position``: ``([contents, ...], end)``."""
    groups = []
    while position < len(text) and text[position] == "{":
        end = skip_balanced_group(text, position)
        groups.append(text[position + 1 : end - 1])
        position = end
    return groups, position


def labels_from_aux(aux_text):
    """``[(label, [field, ...]), ...]`` for every ``\\newlabel`` in an ``.aux``."""
    labels = []
    for line in aux_text.splitlines():
        if not line.startswith(_NEWLABEL):
            continue
        name_start = len(_NEWLABEL) - 1
        name_end = skip_balanced_group(line, name_start)
        if name_end >= len(line) or line[name_end] != "{":
            continue
        value_end = skip_balanced_group(line, name_end)
        fields, _ = _groups(line[name_end + 1 : value_end - 1], 0)
        labels.append((line[name_start + 1 : name_end - 1], fields))
    return labels


def label_definitions(labels, prefix):
    """The ``\\newlabel`` lines ``xr`` would have created, anchors blanked (see module doc)."""
    lines = []
    for name, fields in labels:
        fields = list(fields)
        if len(fields) > HYPERREF_ANCHOR_FIELD:
            fields[HYPERREF_ANCHOR_FIELD] = ""
        lines.append(f"\\newlabel{{{prefix}{name}}}{{" + "".join(f"{{{f}}}" for f in fields) + "}")
    return lines


def resolve_external_documents(text, aux_for):
    """Replace each ``\\externaldocument`` with the labels it would have read.

    ``aux_for(name)`` returns the ``.aux`` text of the referenced document, or ``None`` if it
    is not available. Returns ``(text, resolved, unresolved)``: ``resolved`` is
    ``[(external, label_count), ...]``; ``unresolved`` lists the calls left untouched.
    """
    pieces = []
    previous = 0
    resolved = []
    unresolved: List[ExternalDocument] = []
    for external in find_external_documents(text):
        aux_text = aux_for(external.name)
        if aux_text is None:
            unresolved.append(external)
            continue
        definitions = label_definitions(labels_from_aux(aux_text), external.prefix)
        pieces.append(text[previous : external.start])
        pieces.append("\\makeatletter\n" + "\n".join(definitions) + "\n\\makeatother")
        previous = external.end
        resolved.append((external, len(definitions)))
    pieces.append(text[previous:])
    return "".join(pieces), resolved, unresolved
