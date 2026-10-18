"""Rewrite non-ASCII characters as the LaTeX that produces them.

Two reasons this is not optional. Pdflatex with an older class stops on a character it has no
definition for -- ``! LaTeX Error: Unicode character ... not set up for use with LaTeX`` -- and
production pipelines re-encode files, so a byte that survives your compile may not survive
theirs. A character that *does* compile today is therefore still worth replacing.

The table maps the characters that actually turn up in manuscripts and bibliographies: dashes
that came from a copy-pasted title, a minus sign where a hyphen was meant, smart quotes,
Greek, and accented Latin letters. Accents are not enumerated -- they are decomposed with
``unicodedata`` and reassembled as LaTeX accent commands, which covers the long tail.

Anything left unmapped is an error, never a silent pass-through: the author has to decide
what ``structure<minus>activity`` was supposed to be, and only they know.
"""

import unicodedata
from dataclasses import dataclass
from typing import Optional

from .latex_spans import non_ascii_positions

# Characters whose replacement is a judgement call rather than a decomposition.
DIRECT_REPLACEMENTS = {
    " ": "~",  # no-break space
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    "‒": "--",  # figure dash
    "–": "--",  # en dash
    "—": "---",  # em dash
    "―": "---",  # horizontal bar
    "─": "---",  # box drawing light horizontal, a frequent en-dash mojibake
    "‘": "`",
    "’": "'",
    "‚": ",",
    "“": "``",
    "”": "''",
    "„": ",,",
    "…": r"\ldots{}",
    "′": r"\ensuremath{'}",
    "″": r"\ensuremath{''}",
    "­": "",  # soft hyphen: invisible, and nothing is lost by dropping it
    "​": "",  # zero-width space
    "﻿": "",  # byte-order mark
    "−": r"\ensuremath{-}",
    "×": r"\ensuremath{\times}",
    "÷": r"\ensuremath{\div}",
    "±": r"\ensuremath{\pm}",
    "∓": r"\ensuremath{\mp}",
    "°": r"\ensuremath{^\circ}",
    "·": r"\ensuremath{\cdot}",
    "•": r"\ensuremath{\bullet}",
    "∼": r"\ensuremath{\sim}",
    "≈": r"\ensuremath{\approx}",
    "≠": r"\ensuremath{\neq}",
    "≤": r"\ensuremath{\leq}",
    "≥": r"\ensuremath{\geq}",
    "→": r"\ensuremath{\rightarrow}",
    "←": r"\ensuremath{\leftarrow}",
    "↔": r"\ensuremath{\leftrightarrow}",
    "⇒": r"\ensuremath{\Rightarrow}",
    "∞": r"\ensuremath{\infty}",
    "²": r"\ensuremath{^{2}}",
    "³": r"\ensuremath{^{3}}",
    "¹": r"\ensuremath{^{1}}",
    "½": r"\ensuremath{1/2}",
    "é": None,  # placeholder, filled by the accent machinery below
    "©": r"\textcopyright{}",
    "®": r"\textregistered{}",
    "™": r"\texttrademark{}",
    "§": r"\S{}",
    "¶": r"\P{}",
    "†": r"\dag{}",
    "‡": r"\ddag{}",
    "€": r"\texteuro{}",
    "£": r"\pounds{}",
    "µ": r"\ensuremath{\mu}",
    "Å": r"\AA{}",
}
del DIRECT_REPLACEMENTS["é"]  # kept above only to document that accents are not listed

# Letters with no useful decomposition.
LIGATURES_AND_LETTERS = {
    "ß": r"{\ss}",
    "æ": r"{\ae}",
    "Æ": r"{\AE}",
    "œ": r"{\oe}",
    "Œ": r"{\OE}",
    "ø": r"{\o}",
    "Ø": r"{\O}",
    "ł": r"{\l}",
    "Ł": r"{\L}",
    "ð": r"{\dh}",
    "Ð": r"{\DH}",
    "þ": r"{\th}",
    "Þ": r"{\TH}",
    "ı": r"{\i}",
    "ȷ": r"{\j}",
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

# Combining marks -> the LaTeX accent command that produces them.
COMBINING_ACCENTS = {
    "̀": "`",
    "́": "'",
    "̂": "^",
    "̃": "~",
    "̄": "=",
    "̆": "u",
    "̇": ".",
    "̈": '"',
    "̊": "r",
    "̋": "H",
    "̌": "v",
    "̣": "d",
    "̧": "c",
    "̨": "k",
    "̱": "b",
}

# Greek letters with a LaTeX macro of their own. The capitals that LaTeX has no macro for
# (Alpha, Beta, ...) are typeset as their Latin lookalikes, which is what they are.
GREEK_NAMES = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "varepsilon",
    "ϵ": "epsilon",
    "ζ": "zeta",
    "η": "eta",
    "θ": "theta",
    "ϑ": "vartheta",
    "ι": "iota",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "ξ": "xi",
    "π": "pi",
    "ρ": "rho",
    "ς": "varsigma",
    "σ": "sigma",
    "τ": "tau",
    "υ": "upsilon",
    "φ": "varphi",
    "ϕ": "phi",
    "χ": "chi",
    "ψ": "psi",
    "ω": "omega",
    "Γ": "Gamma",
    "Δ": "Delta",
    "Θ": "Theta",
    "Λ": "Lambda",
    "Ξ": "Xi",
    "Π": "Pi",
    "Σ": "Sigma",
    "Υ": "Upsilon",
    "Φ": "Phi",
    "Ψ": "Psi",
    "Ω": "Omega",
}

GREEK_LOOKALIKES = {
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Χ": "X",
}


@dataclass
class Replacement:
    character: str
    replacement: str
    line: int
    column: int
    source: Optional[str] = None  # "file:line" in the original sources, when known

    def describe(self):
        where = self.source or f"line {self.line}"
        return f"{where}: U+{ord(self.character):04X} {self.character!r} -> {self.replacement}"


class UnmappedCharacterError(Exception):
    """Raised with every unmapped character at once, so one pass fixes them all."""

    def __init__(self, unmapped):
        self.unmapped = unmapped
        super().__init__(self.render())

    def render(self):
        lines = ["non-ASCII characters with no ASCII equivalent in this package's table:", ""]
        for item in self.unmapped:
            name = unicodedata.name(item.character, "unnamed")
            where = item.source or f"flat line {item.line}"
            lines.append(f"  {where}: U+{ord(item.character):04X} ({name}) {item.character!r}")
        lines += [
            "",
            "Fix them in the original .tex/.bib (they are quoted with the file and line they",
            "came from), or extend DIRECT_REPLACEMENTS in processing/unicode_ascii.py.",
        ]
        return "\n".join(lines)


def accent_replacement(character):
    """``{\\'a}`` for a letter that decomposes into base + one combining mark."""
    decomposed = unicodedata.normalize("NFD", character)
    if len(decomposed) != 2:
        return None
    base, mark = decomposed
    if ord(base) > 127 or mark not in COMBINING_ACCENTS:
        return None
    command = COMBINING_ACCENTS[mark]
    separator = "" if not command.isalpha() else " "
    return "{\\" + command + separator + base + "}"


def latex_for(character):
    """The LaTeX that produces ``character``, or ``None`` if it is not in the table."""
    if ord(character) < 128:
        return character
    if character in DIRECT_REPLACEMENTS:
        return DIRECT_REPLACEMENTS[character]
    if character in LIGATURES_AND_LETTERS:
        return LIGATURES_AND_LETTERS[character]
    if character in GREEK_NAMES:
        return "\\ensuremath{\\" + GREEK_NAMES[character] + "}"
    if character in GREEK_LOOKALIKES:
        return GREEK_LOOKALIKES[character]
    accented = accent_replacement(character)
    if accented is not None:
        return accented
    return None


def to_ascii(text, origin_of_line=None):
    """``(ascii_text, replacements)``; raises on anything the table does not cover.

    ``origin_of_line(line_number)`` -- when given -- maps a line of ``text`` back to the file
    and line it came from, so the report and any error point at something the author can edit.
    """
    positions = non_ascii_positions(text)
    if not positions:
        return text, []

    replacements = []
    unmapped = []
    for index, character in positions:
        line = text.count("\n", 0, index) + 1
        column = index - (text.rfind("\n", 0, index) + 1) + 1
        source = None
        if origin_of_line is not None:
            origin = origin_of_line(line)
            if origin is not None:
                source = f"{origin.path}:{origin.line}"
        item = Replacement(
            character=character,
            replacement=latex_for(character) or "",
            line=line,
            column=column,
            source=source,
        )
        if latex_for(character) is None:
            unmapped.append(item)
        else:
            replacements.append(item)

    if unmapped:
        raise UnmappedCharacterError(unmapped)

    pieces = []
    previous = 0
    for index, character in positions:
        pieces.append(text[previous:index])
        pieces.append(latex_for(character))
        previous = index + 1
    pieces.append(text[previous:])
    return "".join(pieces), replacements
