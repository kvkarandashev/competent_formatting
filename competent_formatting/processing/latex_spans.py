"""Tell LaTeX code apart from comments and from text that must never be rewritten.

Every source-rewriting step in this package -- inlining ``\\input``s, stripping comments,
renaming figures, normalising non-ASCII characters -- needs the same answer first: *is this
byte live LaTeX, a comment, or something verbatim that has to survive untouched?* Getting it
wrong is quiet and expensive: a ``%`` in a URL is not a comment, a ``\\input`` inside a comment
is not an input, and an en dash inside ``lstlisting`` is content, not a typo to normalise.

So the scan lives here once, and the rewriters consume spans rather than running their own
regexes over the raw text.

The scanner is deliberately a character walk and not ``pylatexenc``: it has to classify
*source positions* in a file that may not parse as a whole document (a fragment, a ``.bbl``, a
table body), and it must keep byte offsets exact so a caller can splice text back in. The node
tree answers neither question.
"""

import re
from collections import namedtuple

CODE = "code"
COMMENT = "comment"
PROTECTED = "protected"

# A span covers [start, end) of the source. A COMMENT span starts at its `%` and stops
# *before* the newline, which belongs to the following code span -- whether that newline
# survives is the comment stripper's decision, not the scanner's.
Span = namedtuple("Span", ["kind", "start", "end"])

# Environments whose body is copied out verbatim by LaTeX, so nothing inside may be rewritten.
VERBATIM_ENVIRONMENTS = frozenset(
    {
        "verbatim",
        "verbatim*",
        "Verbatim",
        "Verbatim*",
        "lstlisting",
        "minted",
        "alltt",
        "comment",
        "filecontents",
        "filecontents*",
    }
)

# Macros whose whole braced argument is verbatim-ish.
VERBATIM_ARGUMENT_MACROS = frozenset({"url", "nolinkurl", "path", "lstinline", "verbatiminput"})

# Macros whose *first* braced argument only is verbatim-ish (the rest is ordinary text).
FIRST_ARGUMENT_PROTECTED_MACROS = frozenset({"href"})

_MACRO_NAME = re.compile(r"\\([a-zA-Z@]+\*?|.)", re.DOTALL)
_BEGIN_ENVIRONMENT = re.compile(r"\\begin\s*\{([^}]*)\}")


def skip_balanced_group(text, index):
    """Index just past the group starting at ``text[index] == '{'``.

    Returns ``index`` unchanged when there is no group there, so callers can treat "no
    argument" and "argument skipped" uniformly.
    """
    if index >= len(text) or text[index] != "{":
        return index
    depth = 0
    position = index
    while position < len(text):
        character = text[position]
        if character == "\\":
            position += 2
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return len(text)


def _skip_optional_argument(text, index):
    if index < len(text) and text[index] == "[":
        closing = text.find("]", index)
        if closing != -1:
            return closing + 1
    return index


def _skip_whitespace(text, index):
    while index < len(text) and text[index] in " \t":
        index += 1
    return index


def _end_of_verb(text, index):
    """``\\verb|...|``: skip the delimiter pair. The delimiter is the next character."""
    index = _skip_whitespace(text, index)
    if index >= len(text):
        return len(text)
    delimiter = text[index]
    closing = text.find(delimiter, index + 1)
    if closing == -1:
        return len(text)
    return closing + 1


def _end_of_verbatim_environment(text, index, environment):
    closing = re.compile(r"\\end\s*\{" + re.escape(environment) + r"\}")
    match = closing.search(text, index)
    if match is None:
        return len(text)
    return match.end()


def iter_spans(text):
    """Classify the whole source into consecutive ``Span``s covering ``[0, len(text))``."""
    spans = []
    code_start = 0
    position = 0
    length = len(text)

    def close_code(end):
        if end > code_start:
            spans.append(Span(CODE, code_start, end))

    while position < length:
        character = text[position]
        if character == "%":
            close_code(position)
            newline = text.find("\n", position)
            end = length if newline == -1 else newline
            spans.append(Span(COMMENT, position, end))
            position = end
            code_start = position
            continue
        if character != "\\":
            position += 1
            continue

        match = _MACRO_NAME.match(text, position)
        if match is None:  # a trailing lone backslash
            position += 1
            continue
        name = match.group(1)
        after = match.end()

        if name == "begin":
            begin = _BEGIN_ENVIRONMENT.match(text, position)
            if begin is not None and begin.group(1) in VERBATIM_ENVIRONMENTS:
                close_code(position)
                end = _end_of_verbatim_environment(text, begin.end(), begin.group(1))
                spans.append(Span(PROTECTED, position, end))
                position = code_start = end
                continue
            position = after
            continue
        if name in ("verb", "verb*"):
            close_code(position)
            end = _end_of_verb(text, after)
            spans.append(Span(PROTECTED, position, end))
            position = code_start = end
            continue
        if name in VERBATIM_ARGUMENT_MACROS or name in FIRST_ARGUMENT_PROTECTED_MACROS:
            argument_start = _skip_whitespace(text, after)
            argument_start = _skip_optional_argument(text, argument_start)
            argument_start = _skip_whitespace(text, argument_start)
            end = skip_balanced_group(text, argument_start)
            if end > argument_start:
                close_code(position)
                spans.append(Span(PROTECTED, position, end))
                position = code_start = end
                continue
            position = after
            continue

        # Any other escape sequence: the backslash and the name are ordinary code, but they
        # are consumed together so that `\%` is never read as a comment.
        position = after

    close_code(length)
    return spans


def code_spans(text):
    return [span for span in iter_spans(text) if span.kind == CODE]


def comment_spans(text):
    return [span for span in iter_spans(text) if span.kind == COMMENT]


def in_code(spans, index):
    """Whether ``index`` falls inside one of ``spans`` (which must be sorted)."""
    for span in spans:
        if span.start <= index < span.end:
            return True
        if span.start > index:
            return False
    return False


def apply_deletions(text, deletions):
    """Delete ``[start, end)`` ranges, given in any order, and return the result."""
    if not deletions:
        return text
    pieces = []
    previous = 0
    for start, end in sorted(deletions):
        if start < previous:  # overlapping ranges: keep the longest reach
            previous = max(previous, end)
            continue
        pieces.append(text[previous:start])
        previous = end
    pieces.append(text[previous:])
    return "".join(pieces)


def iter_lines(text):
    """``(line_number, start, end)`` per line, 1-based, ``end`` excluding the newline."""
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


def strip_comments_by_line(text):
    """``[(original_line_number, text_without_comment), ...]``, dropped lines omitted.

    Comment stripping never joins or splits lines -- a line is either shortened or deleted
    outright -- so the original line number of everything that survives is known exactly.
    That is what lets an error found in the flattened document be reported against the file
    and line the author actually has to edit.

    Three cases, and the difference between them is visible in the output PDF:

    * ``foo%note`` -- the `%` swallows the newline, so ``foo`` and the next line's first word
      are one word. The comment text goes, a bare ``%`` stays.
    * ``foo %note`` -- there is already a space, so the whole comment goes and the newline
      stays; LaTeX collapses the two spaces.
    * a line that is nothing but a comment -- the entire line goes, because leaving a blank
      line behind would start a paragraph that was not there before.
    """
    cuts = {}
    dropped = set()
    line_of = {}
    lines = iter_lines(text)
    for number, start, end in lines:
        line_of[start] = (number, end)
    for span in comment_spans(text):
        line_start = text.rfind("\n", 0, span.start) + 1
        number, _ = line_of[line_start]
        before = text[line_start : span.start]
        if not before.strip():
            dropped.add(number)
        elif before[-1] in " \t":
            cuts[number] = span.start
        else:
            cuts[number] = span.start + 1
    kept = []
    for number, start, end in lines:
        if number in dropped:
            continue
        kept.append((number, text[start : cuts.get(number, end)]))
    return kept


def strip_comments(text):
    """Comment-stripped source, as a string. See :func:`strip_comments_by_line`."""
    stripped = "\n".join(line for _, line in strip_comments_by_line(text))
    if text.endswith("\n") and stripped:
        stripped += "\n"
    return stripped


def non_ascii_positions(text):
    """``(index, character)`` for every non-ASCII character outside protected spans."""
    protected = [span for span in iter_spans(text) if span.kind == PROTECTED]
    found = []
    protected_index = 0
    for index, character in enumerate(text):
        if ord(character) < 128:
            continue
        while protected_index < len(protected) and protected[protected_index].end <= index:
            protected_index += 1
        if protected_index < len(protected) and protected[protected_index].start <= index:
            continue
        found.append((index, character))
    return found
