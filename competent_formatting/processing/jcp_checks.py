"""The checks that decide whether a submission package is ready, and how it is reported.

Split from the pipeline in ``jcp_source.py`` because these are judgement calls, not
mechanics: what counts as a hard failure, what is only worth a warning, and what a human
needs to read in order to act. Each returns :class:`Check` records; nothing here mutates the
document.

The split between *error* and *warning* follows one rule: an error is something that would
make the uploaded package fail to build or be rejected on sight; a warning is something the
author should look at but may legitimately decide to keep.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from pylatexenc.latex2text import LatexNodes2Text

from .flatten import FLOAT_ENVIRONMENTS, TABLE_ENVIRONMENTS, find_environments, find_macro_calls
from .latex_spans import code_spans

ERROR = "error"
WARNING = "warning"
INFO = "info"

# AIP's limits for a figure as printed (publishing.aip.org author instructions).
MAX_FIGURE_WIDTH_CM = 17.0
MAX_FIGURE_HEIGHT_CM = 21.1
MIN_RASTER_DPI = 300

REVTEX_CLASSES = ("revtex4-1", "revtex4-2")

_DOCUMENTCLASS = re.compile(r"\\documentclass\s*(\[([^\]]*)\])?\s*\{([^}]*)\}")
_USEPACKAGE = re.compile(r"\\usepackage\s*(\[[^\]]*\])?\s*\{([^}]*)\}")
_PLACEHOLDER = re.compile(r"(?<![.\w])(\.\.\.|\u2026)(?![\w])")
_TODO = re.compile(r"\b(TODO|FIXME|XXX)\b")
_DOUBLE_QUESTION = re.compile(r"\?\?")
_STRAIGHT_QUOTE = re.compile(r'"')
_COLOUR_MACRO = re.compile(r"\\(?:text)?color\b|\\colorbox\b")
_REF = re.compile(r"\\(?:eq)?ref\s*\{([^}]*)\}")
_LABEL = re.compile(r"\\label\s*\{([^}]*)\}")

REQUIRED_SECTIONS = {
    "data availability": "Data availability statement (mandatory at AIP)",
    "author declarations": "Author Declarations section",
    "conflict of interest": "Conflict of Interest declaration",
    "author contributions": "Author Contributions (CRediT) statement",
}


@dataclass
class Check:
    level: str
    category: str
    message: str

    def render(self):
        return f"[{self.level}] {self.category}: {self.message}"


@dataclass
class Caption:
    kind: str  # "figure" | "table"
    number: int
    text: str
    label: Optional[str] = None


@dataclass
class DocumentClass:
    name: str = ""
    options: List[str] = field(default_factory=list)
    packages: List[str] = field(default_factory=list)  # in order, duplicates kept


def parse_class_and_packages(text):
    """Document class, its options, and every package loaded, in order."""
    parsed = DocumentClass()
    for span in code_spans(text):
        match = _DOCUMENTCLASS.search(text, span.start, span.end)
        if match is not None:
            parsed.name = match.group(3).strip()
            parsed.options = [
                option.strip() for option in (match.group(2) or "").split(",") if option.strip()
            ]
            break
    for span in code_spans(text):
        for match in _USEPACKAGE.finditer(text, span.start, span.end):
            parsed.packages += [name.strip() for name in match.group(2).split(",") if name.strip()]
    return parsed


def check_class(parsed):
    """AIP wants RevTeX with the ``aip`` option, in ``preprint`` layout for review."""
    checks = []
    if parsed.name not in REVTEX_CLASSES:
        checks.append(
            Check(
                WARNING,
                "class",
                f"document class is {parsed.name!r}, not one of {', '.join(REVTEX_CLASSES)}; "
                "AIP's template is RevTeX and a different class may delay production",
            )
        )
        return checks
    if "aip" not in parsed.options:
        checks.append(
            Check(
                WARNING,
                "class",
                "the 'aip' class option is missing; RevTeX needs it to produce AIP's layout",
            )
        )
    if "reprint" in parsed.options:
        checks.append(
            Check(
                WARNING,
                "class",
                "'reprint' is set; AIP asks for 'preprint' for review and production, and a "
                "manuscript that does not format under 'preprint' may be delayed",
            )
        )
    elif "preprint" not in parsed.options:
        checks.append(
            Check(
                INFO,
                "class",
                "neither 'preprint' nor 'reprint' is set; AIP uses 'preprint' for review",
            )
        )
    return checks


def check_duplicate_packages(parsed):
    seen = set()
    duplicates = []
    for package in parsed.packages:
        if package in seen and package not in duplicates:
            duplicates.append(package)
        seen.add(package)
    if not duplicates:
        return []
    return [
        Check(
            WARNING,
            "packages",
            f"loaded more than once: {', '.join(duplicates)} (harmless, but untidy in a "
            "source package someone else will compile)",
        )
    ]


def captions(text):
    """Figure and table captions in document order, as plain text."""
    converter = LatexNodes2Text(keep_comments=False)
    floats = find_environments(text, FLOAT_ENVIRONMENTS + TABLE_ENVIRONMENTS)
    caption_calls = [call for call in find_macro_calls(text, {"caption"}) if call[3] is not None]
    labels = [(match.start(), match.group(1)) for match in _LABEL.finditer(text)]

    numbers = {"figure": 0, "table": 0}
    found = []
    for name, outer_start, _, body_end, _ in floats:
        kind = "figure" if name.startswith("figure") else "table"
        numbers[kind] += 1
        inside = [call for call in caption_calls if outer_start < call[1] < body_end]
        if not inside:
            continue
        label = next(
            (value for position, value in labels if outer_start < position < body_end), None
        )
        raw = inside[0][3]
        try:
            plain = converter.latex_to_text(raw)
        except Exception:  # pragma: no cover - pylatexenc is tolerant, but never fail here
            plain = raw
        plain = " ".join(plain.split())
        found.append(Caption(kind=kind, number=numbers[kind], text=plain, label=label))
    return found


def alt_text_draft(main_captions, si_captions=()):
    """The ``alt_text.txt`` AIP asks for: one entry per figure and table, numbered."""
    lines = [
        "Alt text for every figure and table, in the order they appear.",
        "",
        "Alt text should describe what the reader would see -- the visual content -- for",
        "someone who cannot see it. It is not the caption again: the caption says what the",
        "figure means, the alt text says what it looks like. Replace every TODO below.",
        "",
    ]
    for prefix, group in (("", main_captions), ("S", si_captions)):
        for caption in group:
            label = f"{caption.kind.capitalize()} {prefix}{caption.number}"
            lines.append(f"{label}. {caption.text}")
            lines.append("Alt text: TODO")
            lines.append("")
    return "\n".join(lines)


def lint_prose(text):
    """Things a reader of the submitted PDF would notice, none of them fatal."""
    checks = []
    lowered = text.lower()
    for key, description in REQUIRED_SECTIONS.items():
        if key not in lowered:
            checks.append(Check(WARNING, "lint", f"no {description} found"))

    for span in code_spans(text):
        chunk = text[span.start : span.end]
        offset = span.start
        for match in _PLACEHOLDER.finditer(chunk):
            checks.append(
                Check(
                    WARNING,
                    "lint",
                    f"placeholder '...' at line {text.count(chr(10), 0, offset + match.start()) + 1}"
                    " -- an unfilled reference or URL?",
                )
            )
        for match in _TODO.finditer(chunk):
            checks.append(
                Check(
                    WARNING,
                    "lint",
                    f"{match.group(1)} left at line "
                    f"{text.count(chr(10), 0, offset + match.start()) + 1}",
                )
            )
        for match in _DOUBLE_QUESTION.finditer(chunk):
            checks.append(
                Check(
                    WARNING,
                    "lint",
                    f"'??' at line {text.count(chr(10), 0, offset + match.start()) + 1} -- an "
                    "unresolved reference in the source, not just in the PDF",
                )
            )
        for match in _COLOUR_MACRO.finditer(chunk):
            checks.append(
                Check(
                    WARNING,
                    "lint",
                    f"colour command at line "
                    f"{text.count(chr(10), 0, offset + match.start()) + 1} survived cleaning "
                    "-- stale revision markup?",
                )
            )
    straight = _count_straight_quotes(text)
    if straight:
        checks.append(
            Check(
                WARNING,
                "lint",
                f'{straight} straight double quote(s) in text; LaTeX renders " as a closing '
                "quote, so an opening one needs ``",
            )
        )
    return checks


def _count_straight_quotes(text):
    count = 0
    for span in code_spans(text):
        chunk = text[span.start : span.end]
        count += len(_STRAIGHT_QUOTE.findall(chunk))
    return count


def check_float_citation_order(text):
    """AIP wants floats first cited in numerical order."""
    checks = []
    label_numbers = {}
    for caption in captions(text):
        if caption.label:
            label_numbers[caption.label] = (caption.kind, caption.number)

    first_reference = {}
    for span in code_spans(text):
        for match in _REF.finditer(text, span.start, span.end):
            label = match.group(1)
            if label in label_numbers and label not in first_reference:
                first_reference[label] = match.start()

    for kind in ("figure", "table"):
        ordered = sorted(
            (
                (position, label_numbers[label][1])
                for label, position in first_reference.items()
                if label_numbers[label][0] == kind
            )
        )
        numbers = [number for _, number in ordered]
        if numbers != sorted(numbers):
            checks.append(
                Check(
                    WARNING,
                    "lint",
                    f"{kind}s are first cited out of numerical order ({numbers}); AIP asks for "
                    "floats to be first cited in order",
                )
            )
    return checks


def render_report(result):
    """The ``report.md`` the CLI also prints."""
    lines = [f"# JCP source package: {os.path.basename(result.main_name)}", ""]
    lines.append(f"- output directory: `{result.out_dir}`")
    lines.append(f"- flat source: `{os.path.join('source', result.main_name)}`")
    if result.pdf_path:
        lines.append(f"- author PDF: `{os.path.basename(result.pdf_path)}`")
    if result.sm_pdf_path:
        lines.append(f"- supplementary PDF: `{os.path.basename(result.sm_pdf_path)}`")
    if result.marked_pdf_path:
        lines.append(f"- marked PDF: `{os.path.basename(result.marked_pdf_path)}`")
    if result.sm_marked_pdf_path:
        lines.append(
            f"- marked supplementary PDF: `{os.path.basename(result.sm_marked_pdf_path)}`"
        )
    if result.zip_path:
        lines.append(f"- upload archive: `{os.path.basename(result.zip_path)}`")
    lines.append("")

    errors = [check for check in result.checks if check.level == ERROR]
    warnings = [check for check in result.checks if check.level == WARNING]
    infos = [check for check in result.checks if check.level == INFO]

    lines.append(
        f"**{'FAILED' if errors else 'PASSED'}** "
        f"-- {len(errors)} hard failure(s), {len(warnings)} warning(s)."
    )
    lines.append("")

    for title, group in (
        ("Hard failures", errors),
        ("Warnings", warnings),
        ("Notes", infos),
    ):
        if not group:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for check in group:
            lines.append(f"- **{check.category}**: {check.message}")
        lines.append("")

    if result.figure_map:
        lines += ["## Figures", "", "| source | shipped as |", "|---|---|"]
        for original, new in result.figure_map:
            lines.append(f"| `{original}` | `{new}` |")
        lines.append("")

    if result.replacements:
        lines += ["## Non-ASCII characters replaced", ""]
        grouped = {}
        for replacement in result.replacements:
            grouped.setdefault(replacement.source or "(flat document)", []).append(replacement)
        for source in sorted(grouped):
            lines.append(f"- `{source}`")
            for replacement in grouped[source]:
                lines.append(
                    f"  - U+{ord(replacement.character):04X} `{replacement.character}` -> "
                    f"`{replacement.replacement}`"
                )
        lines += [
            "",
            "These were fixed in the shipped copy only. The originals still hold them, so the",
            "same replacements will be needed again unless the `.tex`/`.bib` are corrected.",
            "",
        ]

    if result.page_counts:
        built, verified = result.page_counts
        lines += [
            "## Page counts",
            "",
            f"- full build (BibTeX): {built}",
            f"- verified flat build (pdflatex only): {verified}",
            "",
        ]

    if result.bibtex_warnings:
        lines += ["## BibTeX warnings", ""]
        lines += [f"- {warning}" for warning in result.bibtex_warnings]
        lines.append("")

    return "\n".join(lines) + "\n"
