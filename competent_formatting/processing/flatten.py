"""Turn a multi-file manuscript into one self-contained ``.tex``.

A journal wants a flat directory: one source file, figures beside it under plain names, no
subdirectories. A working manuscript is the opposite -- ``\\input``s per section or table,
figures in nested folders, a ``\\graphicspath``. This module performs that collapse, and the
one thing it must not lose on the way is **provenance**: an error found in the flattened text
is useless unless it names the file and line the author has to edit.

That is why flattening happens line by line rather than by string substitution. Comment
stripping deletes or shortens lines but never joins them (see
:func:`..latex_spans.strip_comments_by_line`), so every output line can be traced back to one
``(file, line)`` pair, through any depth of ``\\input``.

``\\input`` substitution is in-place, exactly as TeX does it: text before the macro and the
first line of the inlined file share an output line, and so do the inlined file's last line
and whatever followed the macro. Anything else would insert spaces the author did not write.
"""

import os
import re
from collections import namedtuple
from dataclasses import dataclass, field
from typing import List, Optional

from .latex_spans import code_spans, iter_spans, skip_balanced_group, strip_comments_by_line

Origin = namedtuple("Origin", ["path", "line"])

TEX_EXTENSION = ".tex"

# Extensions pdflatex tries, in its own order, when \includegraphics names no extension.
GRAPHICS_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".tif", ".tiff")

# Inlining these would need information the flat file cannot carry: another document's .aux,
# or a search path resolved at compile time. Failing loudly beats shipping a file that
# silently lost a section.
UNSUPPORTED_MACROS = {
    "subfile": "\\subfile (the subfiles package) -- inline it by hand first",
    "import": "\\import (the import package) -- inline it by hand first",
    "subimport": "\\subimport (the import package) -- inline it by hand first",
    "InputIfFileExists": "\\InputIfFileExists -- replace it with a plain \\input",
    "externaldocument": "\\externaldocument -- the main file cannot reference another document",
}

_MACRO_CALL = re.compile(r"\\([a-zA-Z@]+)\*?")
_INCLUDEGRAPHICS = re.compile(r"\\includegraphics\s*\*?\s*(\[[^\]]*\])?\s*\{([^}]*)\}")
_GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{")
_ENVIRONMENT_DELIMITER = re.compile(r"\\(begin|end)\s*\{([^}]*)\}")

FLOAT_ENVIRONMENTS = ("figure", "figure*")
TABLE_ENVIRONMENTS = ("table", "table*")


class FlattenError(Exception):
    """Raised when the document cannot be flattened without losing something."""


@dataclass
class FlatDocument:
    text: str
    origins: List[Origin]  # one per line of `text`, 0-indexed by line
    inputs: List[str] = field(default_factory=list)

    def origin_of_line(self, line_number):
        """``Origin`` of 1-based output line ``line_number``, or ``None``."""
        index = line_number - 1
        if 0 <= index < len(self.origins):
            return self.origins[index]
        return None

    def origin_of_offset(self, offset):
        return self.origin_of_line(self.text.count("\n", 0, offset) + 1)


class _LineAccumulator:
    """Collects output lines, remembering which source line opened each one."""

    def __init__(self):
        self.lines = []
        self.origins = []
        self._open = None
        self._open_origin = None

    def write(self, text, origin):
        # An empty write must not claim the line: the text before an \input is empty
        # whenever the macro starts the line, and the line then belongs to the file being
        # inlined, not to the one holding the \input.
        if not text:
            return
        if self._open is None:
            self._open = []
            self._open_origin = origin
        self._open.append(text)

    def newline(self, origin):
        if self._open is None:
            self._open = []
            self._open_origin = origin
        self.lines.append("".join(self._open))
        self.origins.append(self._open_origin)
        self._open = None
        self._open_origin = None

    def finish(self):
        if self._open is not None:
            self.newline(self._open_origin)
        return "\n".join(self.lines) + "\n", list(self.origins)


def _read(path):
    with open(path, "r", encoding="utf-8", errors="strict") as handle:
        return handle.read()


def resolve_input(name, root, current_dir):
    """Resolve an ``\\input`` argument the way TeX does, or return ``None``.

    TeX looks relative to the working directory, which for a manuscript is the directory of
    the main file; a relative path next to the *including* file is tried as well, because
    that is what authors expect even though TeX does not do it.
    """
    candidates = []
    for base in (root, current_dir):
        candidate = os.path.normpath(os.path.join(base, name))
        candidates.append(candidate)
        if not os.path.splitext(candidate)[1]:
            candidates.append(candidate + TEX_EXTENSION)
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _input_calls(text):
    """``(start, end, macro, argument)`` for every input-like macro in live code."""
    spans = code_spans(text)
    calls = []
    for span in spans:
        for match in _MACRO_CALL.finditer(text, span.start, span.end):
            name = match.group(1)
            if name in UNSUPPORTED_MACROS:
                calls.append((match.start(), match.end(), name, None))
                continue
            if name not in ("input", "include"):
                continue
            position = match.end()
            while position < len(text) and text[position] in " \t":
                position += 1
            if position < len(text) and text[position] == "{":
                end = skip_balanced_group(text, position)
                calls.append((match.start(), end, name, text[position + 1 : end - 1].strip()))
                continue
            # \input filename -- plain TeX form, terminated by whitespace.
            end = position
            while end < len(text) and text[end] not in " \t\n%{}\\":
                end += 1
            if end > position:
                calls.append((match.start(), end, name, text[position:end]))
    return sorted(calls)


def _flatten_file(path, root, accumulator, keep_comments, stack, inputs):
    real = os.path.realpath(path)
    if real in stack:
        chain = " -> ".join(os.path.relpath(item, root) for item in [*stack, real])
        raise FlattenError(f"\\input cycle: {chain}")
    stack = [*stack, real]
    relative = os.path.relpath(path, root)
    text = _read(path)
    if keep_comments:
        lines = [(number, text[start:end]) for number, start, end in _plain_lines(text)]
    else:
        lines = strip_comments_by_line(text)

    calls = _input_calls(text)
    by_line = {}
    line_bounds = {number: (start, end) for number, start, end in _plain_lines(text)}
    for start, end, name, argument in calls:
        line_number = text.count("\n", 0, start) + 1
        by_line.setdefault(line_number, []).append((start, end, name, argument))

    for index, (line_number, content) in enumerate(lines):
        origin = Origin(relative, line_number)
        line_start, line_end = line_bounds[line_number]
        here = by_line.get(line_number, [])
        for start, end, name, argument in here:
            if end > line_end and name not in UNSUPPORTED_MACROS:
                # The argument runs onto the next line. Legal TeX, but splicing is done at
                # line granularity, so refuse rather than leave a live \input in the output
                # for the verification build to trip over.
                raise FlattenError(
                    f"{relative}:{line_number}: \\{name} with an argument spanning lines; "
                    "put it on one line"
                )
        cursor = 0
        for start, end, name, argument in here:
            if name in UNSUPPORTED_MACROS:
                raise FlattenError(
                    f"{relative}:{line_number}: {UNSUPPORTED_MACROS[name]}",
                )
            column_start, column_end = start - line_start, end - line_start
            if column_start < cursor or column_end > len(content):
                # The call was cut off by comment stripping (it sat inside a comment that
                # began earlier on the line); nothing to inline.
                continue
            accumulator.write(content[cursor:column_start], origin)
            target = resolve_input(argument, root, os.path.dirname(path))
            if target is None:
                raise FlattenError(
                    f"{relative}:{line_number}: \\{name}{{{argument}}} -- no such file "
                    f"(looked next to {os.path.relpath(root, root) or '.'} and "
                    f"{os.path.relpath(os.path.dirname(path), root) or '.'})"
                )
            inputs.append(os.path.relpath(target, root))
            if name == "include":
                # \include implies a page break on both sides; keep the pagination the
                # author had rather than silently reflowing the document.
                accumulator.write("\\clearpage", origin)
                accumulator.newline(origin)
            _flatten_file(target, root, accumulator, keep_comments, stack, inputs)
            if name == "include":
                accumulator.newline(origin)
                accumulator.write("\\clearpage", origin)
            cursor = column_end
        accumulator.write(content[cursor:], origin)
        if index < len(lines) - 1:
            accumulator.newline(origin)


def _plain_lines(text):
    lines = []
    start = 0
    number = 1
    while start <= len(text):
        newline = text.find("\n", start)
        if newline == -1:
            if start < len(text):
                lines.append((number, start, len(text)))
            break
        lines.append((number, start, newline))
        start = newline + 1
        number += 1
    return lines


def flatten(main_tex, root=None, keep_comments=False):
    """Inline every ``\\input``/``\\include`` of ``main_tex`` into one :class:`FlatDocument`."""
    main_tex = os.path.abspath(main_tex)
    if root is None:
        root = os.path.dirname(main_tex)
    root = os.path.abspath(root)
    if not os.path.isfile(main_tex):
        raise FlattenError(f"no such file: {main_tex}")
    accumulator = _LineAccumulator()
    inputs = []
    _flatten_file(main_tex, root, accumulator, keep_comments, [], inputs)
    text, origins = accumulator.finish()
    return FlatDocument(text=text, origins=origins, inputs=inputs)


# ==================================================================================
# Environments and floats
# ==================================================================================


def find_environments(text, names=None):
    """``[(name, outer_start, body_start, body_end, outer_end), ...]`` in order of ``\\begin``.

    Only live code is searched, so a ``\\begin{figure}`` inside a comment or a verbatim block
    is not an environment. Unbalanced ``\\end``s are ignored rather than raising: this runs on
    documents that LaTeX itself accepts, and an ``\\end`` with no ``\\begin`` is the author's
    problem to see in the compile log, not a reason to refuse to package.
    """
    wanted = None if names is None else set(names)
    found = []
    stack = []
    for span in code_spans(text):
        for match in _ENVIRONMENT_DELIMITER.finditer(text, span.start, span.end):
            kind, name = match.group(1), match.group(2)
            if kind == "begin":
                stack.append((name, match.start(), match.end()))
                continue
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == name:
                    open_name, outer_start, body_start = stack.pop(index)
                    del stack[index:]
                    if wanted is None or open_name in wanted:
                        found.append(
                            (open_name, outer_start, body_start, match.start(), match.end())
                        )
                    break
    return sorted(found, key=lambda item: item[1])


# ==================================================================================
# Graphics
# ==================================================================================


@dataclass
class GraphicUse:
    start: int
    end: int
    options: str
    path: str
    float_number: Optional[int] = None  # 1-based index of the enclosing figure environment
    suffix: str = ""  # "a", "b", ... when one float holds several graphics


def graphicspath_directories(text):
    """``(directories, spans)``: what ``\\graphicspath`` adds, and where to delete it."""
    directories = []
    spans = []
    for span in code_spans(text):
        for match in _GRAPHICSPATH.finditer(text, span.start, span.end):
            end = skip_balanced_group(text, match.end() - 1)
            body = text[match.end() : end - 1]
            directories += [item.strip() for item in re.findall(r"\{([^}]*)\}", body)]
            spans.append((match.start(), end))
    return directories, spans


def find_graphics(text):
    """Every ``\\includegraphics`` in live code, numbered by its enclosing figure float.

    Figure environments are numbered in order of appearance, so ``fig3.pdf`` is the graphic of
    the document's third figure -- the number the caption will carry. A float holding several
    graphics gets letters (``fig3a``, ``fig3b``); a graphic outside any float is numbered
    separately as ``graphicN``.
    """
    floats = [
        (outer_start, outer_end)
        for _, outer_start, _, _, outer_end in find_environments(text, FLOAT_ENVIRONMENTS)
    ]
    uses = []
    spans = code_spans(text)
    for span in spans:
        for match in _INCLUDEGRAPHICS.finditer(text, span.start, span.end):
            uses.append(
                GraphicUse(
                    start=match.start(),
                    end=match.end(),
                    options=match.group(1) or "",
                    path=match.group(2).strip(),
                )
            )
    uses.sort(key=lambda use: use.start)

    per_float = {}
    for use in uses:
        for number, (start, end) in enumerate(floats, start=1):
            if start <= use.start < end:
                use.float_number = number
                per_float.setdefault(number, []).append(use)
                break
    for number, group in per_float.items():
        if len(group) > 1:
            for index, use in enumerate(group):
                use.suffix = chr(ord("a") + index) if index < 26 else f"_{index + 1}"
    return uses


def resolve_graphic(name, root, directories=()):
    """Find the file ``\\includegraphics{name}`` refers to, or ``None``."""
    bases = [root, *[os.path.join(root, directory) for directory in directories]]
    for base in bases:
        candidate = os.path.normpath(os.path.join(base, name))
        if os.path.splitext(candidate)[1] and os.path.isfile(candidate):
            return candidate
        for extension in GRAPHICS_EXTENSIONS:
            if os.path.isfile(candidate + extension):
                return candidate + extension
        # "figures/plot.main" -- a dot in the stem is not an extension.
        if os.path.isfile(candidate):
            return candidate
    return None


def assign_graphic_names(uses, resolved, prefix="fig"):
    """``{use_index: output_name}``; the same source file always gets one name."""
    names = {}
    by_source = {}
    outside_counter = 0
    for index, use in enumerate(uses):
        source = resolved[index]
        if source in by_source:
            names[index] = by_source[source]
            continue
        extension = os.path.splitext(source)[1].lower()
        if use.float_number is None:
            outside_counter += 1
            stem = f"graphic{outside_counter}"
        else:
            stem = f"{prefix}{use.float_number}{use.suffix}"
        names[index] = stem + extension
        by_source[source] = names[index]
    return names


def rewrite_graphics(text, uses, names):
    """Replace each ``\\includegraphics`` argument with its flat output name."""
    pieces = []
    previous = 0
    for index, use in enumerate(uses):
        pieces.append(text[previous : use.start])
        pieces.append("\\includegraphics" + use.options + "{" + names[index] + "}")
        previous = use.end
    pieces.append(text[previous:])
    return "".join(pieces)


def remove_spans(text, spans):
    pieces = []
    previous = 0
    for start, end in sorted(spans):
        pieces.append(text[previous:start])
        previous = end
    pieces.append(text[previous:])
    return "".join(pieces)


def find_macro_calls(text, names):
    """``[(name, start, end, argument), ...]`` for ``\\name{...}`` macros in live code."""
    calls = []
    for span in code_spans(text):
        for match in _MACRO_CALL.finditer(text, span.start, span.end):
            name = match.group(1)
            if name not in names:
                continue
            position = match.end()
            while position < len(text) and text[position] in " \t\n":
                position += 1
            if position < len(text) and text[position] == "[":
                closing = text.find("]", position)
                position = closing + 1 if closing != -1 else position
                while position < len(text) and text[position] in " \t\n":
                    position += 1
            if position < len(text) and text[position] == "{":
                end = skip_balanced_group(text, position)
                calls.append((name, match.start(), end, text[position + 1 : end - 1]))
            else:
                calls.append((name, match.start(), match.end(), None))
    return sorted(calls, key=lambda call: call[1])


def protected_spans(text):
    return [(span.start, span.end) for span in iter_spans(text) if span.kind == "protected"]
