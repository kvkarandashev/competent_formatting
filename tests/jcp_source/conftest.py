"""A small but realistic manuscript to package, written fresh into ``tmp_path``.

Nothing binary is committed: the figure is compiled on the spot by the one test that needs a
compilable one. Everything the integration test asserts is present here on purpose -- an
``\\input``, a figure in a nested folder, revision markup in both forms, a comment holding a
word that must not reach the package, a footnote citation (which needs a second BibTeX pass
under RevTeX) and a non-ASCII character that only reaches the output through the ``.bbl``.
"""

import shutil
import subprocess

import pytest

MAIN_TEX = r"""\documentclass[aip,jcp,preprint]{revtex4-2}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{amsmath}

\newif\ifshowrevisions
\showrevisionstrue
\ifshowrevisions
  \newcommand{\rev}[1]{{\color{red}#1}}
  \newenvironment{revblock}{\color{red}}{}
\else
  \newcommand{\rev}[1]{#1}
  \newenvironment{revblock}{}{}
\fi
\newcommand{\authorcomment}[1]{}

\begin{document}
\title{A tiny manuscript}
\author{A. Author}
\affiliation{Nowhere}
\begin{abstract}
We test packaging. % SECRET internal note
\end{abstract}
\maketitle

\section{Introduction}
Ordinary text with a citation~\cite{example} and a footnote.%
\footnote{A note that cites \cite{secondary}, which needs a second BibTeX pass.}
\rev{This sentence was added during revision.}
\authorcomment{SECRET reviewer note}

\begin{revblock}
A whole block added during revision, with \rev{nesting} inside.
\end{revblock}

% A whole-line comment mentioning SECRET that must not survive.
Values are given as 1--2~eV.

\begin{figure}[ht]
\includegraphics[width=0.4\textwidth]{figures/sub/f}
\caption{A square.}
\label{fig:square}
\end{figure}

Figure~\ref{fig:square} shows a square and Table~\ref{tab:values} the values.

\input{tables/values}

\section*{Data availability}
The data are openly available.

\section*{Author Declarations}
\subsection*{Conflict of Interest}
The author has no conflicts to disclose.
\subsection*{Author Contributions}
A. Author: everything.

\bibliography{references}
\end{document}
"""

TABLE_TEX = r"""\begin{table}[ht]
\caption{Values measured in this work.}
\label{tab:values}
\begin{tabular}{lc}
\hline
case & value \\
\hline
a & 1.0 \\
b & 2.0 \\
\hline
\end{tabular}
\end{table}
"""

REFERENCES_BIB = """@article{example,
  author = {Author, A. and Coauthor, B.},
  title = {A title with an en–dash inside},
  journal = {J. Chem. Phys.},
  volume = {1},
  pages = {1},
  year = {2026},
}

@article{secondary,
  author = {Second, C.},
  title = {Cited only from a footnote},
  journal = {J. Chem. Phys.},
  volume = {2},
  pages = {2},
  year = {2026},
}
"""

SM_TEX = r"""\documentclass[aip,jcp,preprint]{revtex4-2}
\usepackage{graphicx}
\usepackage{xr-hyper}
\usepackage{hyperref}
\externaldocument[M-]{main}
\newcommand{\rev}[1]{{\color{red}#1}}
\newenvironment{revblock}{\color{red}}{}
\begin{document}
\title{Supplementary Material}
\author{A. Author}
\affiliation{Nowhere}
\maketitle
\section{Extra}
\rev{See Fig.~\ref{M-fig:square} of the main text.}
\begin{figure}[ht]
\includegraphics[width=0.4\textwidth]{figures/sub/f.pdf}
\caption{The same square again.}
\label{fig:sm_square}
\end{figure}
\end{document}
"""

# A latexmkrc with a custom rule, so the package is proved not to depend on one.
LATEXMKRC = "$pdf_mode = 1;\n"

FIGURE_SOURCE = r"""\documentclass[border=2pt]{standalone}
\begin{document}
\rule{2cm}{2cm}
\end{document}
"""


def write_manuscript(root, with_figure=True):
    """Write the manuscript into ``root``; the figure is a placeholder unless compiled."""
    (root / "tables").mkdir(parents=True, exist_ok=True)
    (root / "figures" / "sub").mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (root / "sm.tex").write_text(SM_TEX, encoding="utf-8")
    (root / "tables" / "values.tex").write_text(TABLE_TEX, encoding="utf-8")
    (root / "references.bib").write_text(REFERENCES_BIB, encoding="utf-8")
    (root / "latexmkrc").write_text(LATEXMKRC, encoding="utf-8")
    if with_figure:
        (root / "figures" / "sub" / "f.pdf").write_bytes(b"%PDF-1.4 placeholder\n")
    return root / "main.tex"


def compile_figure(root):
    """Replace the placeholder with a real one-page PDF, built here rather than committed."""
    source = root / "_figure.tex"
    source.write_text(FIGURE_SOURCE, encoding="utf-8")
    subprocess.run(
        ["pdflatex", "-interaction=batchmode", source.name],
        cwd=root,
        capture_output=True,
    )
    built = root / "_figure.pdf"
    if not built.is_file():
        return False
    shutil.copy2(built, root / "figures" / "sub" / "f.pdf")
    for leftover in root.glob("_figure.*"):
        leftover.unlink()
    return True


def have_tex():
    """Whether this machine can compile the fixture at all."""
    for command in ("pdflatex", "latexmk", "bibtex", "kpsewhich"):
        if shutil.which(command) is None:
            return False
    found = subprocess.run(
        ["kpsewhich", "revtex4-2.cls"], capture_output=True, text=True
    ).stdout.strip()
    return bool(found)


@pytest.fixture
def manuscript(tmp_path):
    """The manuscript directory, with a placeholder figure (no TeX needed)."""
    root = tmp_path / "project"
    root.mkdir()
    write_manuscript(root)
    return root


@pytest.fixture(scope="module")
def packaged(tmp_path_factory):
    """The fixture manuscript, packaged once for the whole integration module.

    Module-scoped because it compiles the manuscript several times over (full build, isolated
    verification, supplementary material, marked copies) and every assertion reads the same result.
    """
    from competent_formatting.processing.jcp_source import build_jcp_source

    if not have_tex():
        pytest.skip("needs a TeX installation with revtex4-2")
    root = tmp_path_factory.mktemp("project")
    main = write_manuscript(root)
    if not compile_figure(root):
        pytest.skip("could not compile the test figure")
    out = tmp_path_factory.mktemp("submission") / "package"
    return build_jcp_source(
        str(main),
        str(out),
        si=str(root / "sm.tex"),
        opened_macros=["rev"],
        removed_macros=["authorcomment"],
        opened_envs=["revblock"],
        marked_pdf=True,
    )
