"""Resolving \\externaldocument into the labels it would have read. No TeX needed."""

from competent_formatting.processing.external_labels import (
    find_external_documents,
    label_definitions,
    labels_from_aux,
    resolve_external_documents,
)

AUX = r"""\relax
\newlabel{sec:intro}{{I}{2}{Introduction}{section.1}{}}
\newlabel{eq:b}{{7}{6}{A title with {braces} inside}{equation.7}{}}
\newlabel{plain}{{3}{4}}
\bibcite{x}{{1}{}{}{}}
"""


def test_the_call_is_found_with_its_prefix_name_and_url():
    text = "% \\externaldocument[X-]{commented}\n\\externaldocument[M-]{main}[https://a.b/m.pdf]\n"
    (found,) = find_external_documents(text)
    assert (found.prefix, found.name, found.url) == ("M-", "main", "https://a.b/m.pdf")
    assert text[found.start : found.end] == "\\externaldocument[M-]{main}[https://a.b/m.pdf]"


def test_labels_are_read_with_balanced_braces_and_bibcites_ignored():
    labels = dict(labels_from_aux(AUX))
    assert sorted(labels) == ["eq:b", "plain", "sec:intro"]
    assert labels["eq:b"][2] == "A title with {braces} inside"
    assert labels["plain"] == ["3", "4"]


def test_the_hyperref_anchor_is_blanked_so_no_link_points_into_this_pdf():
    lines = label_definitions(labels_from_aux(AUX), "M-")
    assert "\\newlabel{M-sec:intro}{{I}{2}{Introduction}{}{}}" in lines
    assert "\\newlabel{M-plain}{{3}{4}}" in lines


def test_the_call_is_replaced_and_an_unknown_document_left_alone():
    text = "pre\n\\externaldocument[M-]{main}\n\\externaldocument{other}\npost\n"
    resolved_text, resolved, unresolved = resolve_external_documents(
        text, lambda name: AUX if name == "main" else None
    )
    assert "\\externaldocument[M-]{main}" not in resolved_text
    assert "\\newlabel{M-sec:intro}" in resolved_text
    assert "\\externaldocument{other}" in resolved_text
    assert resolved[0][1] == 3
    assert [external.name for external in unresolved] == ["other"]
