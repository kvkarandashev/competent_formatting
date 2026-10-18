#!/bin/bash
# Package a manuscript for a J. Chem. Phys. source upload, end to end.
#
# Builds a small RevTeX manuscript in a temporary directory -- one \input, a figure in a
# nested folder, revision markup as both a macro and an environment, a footnote citation and
# a non-ASCII character in the .bib -- then packages it and prints the report.
#
# Requires a TeX installation with revtex4-2 (pdflatex, latexmk, bibtex).

set -e

example_dir=$(mktemp -d)
project="$example_dir/project"
mkdir -p "$project/tables" "$project/figures/sub"
trap 'echo; echo "example left in $example_dir"' EXIT

cat > "$project/main.tex" <<'TEX'
\documentclass[aip,jcp,preprint]{revtex4-2}
\usepackage{graphicx}

\newcommand{\rev}[1]{{\color{red}#1}}
\newenvironment{revblock}{\color{red}}{}
\newcommand{\authorcomment}[1]{}

\begin{document}
\title{Packaging example}
\author{A. Author}
\affiliation{Nowhere}
\begin{abstract}
A manuscript with everything that usually breaks a submission. % an internal note
\end{abstract}
\maketitle

\section{Introduction}
Text with a citation~\cite{example} and a footnote.%
\footnote{A footnote that cites \cite{secondary}: this needs a second BibTeX pass.}
\rev{A sentence added during revision.}
\authorcomment{a note to a co-author, dropped entirely}

\begin{revblock}
A block added during revision.
\end{revblock}

\begin{figure}[ht]
\includegraphics[width=0.4\textwidth]{figures/sub/square}
\caption{A square.}
\label{fig:square}
\end{figure}

Figure~\ref{fig:square} shows a square; the values are in Table~\ref{tab:values}.

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
TEX

cat > "$project/tables/values.tex" <<'TEX'
\begin{table}[ht]
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
TEX

# The en dash below reaches the output through the .bbl and is normalised there.
cat > "$project/references.bib" <<'BIB'
@article{example,
  author = {Author, A.},
  title = {A title with an en–dash inside},
  journal = {J. Chem. Phys.}, volume = {1}, pages = {1}, year = {2026},
}
@article{secondary,
  author = {Second, C.},
  title = {Cited only from a footnote},
  journal = {J. Chem. Phys.}, volume = {2}, pages = {2}, year = {2026},
}
BIB

cat > "$example_dir/square.tex" <<'TEX'
\documentclass[border=2pt]{standalone}
\begin{document}
\rule{2cm}{2cm}
\end{document}
TEX
(cd "$example_dir" && pdflatex -interaction=batchmode square.tex > /dev/null)
cp "$example_dir/square.pdf" "$project/figures/sub/square.pdf"

echo "manuscript: $project"
echo

cf_jcp_source "$project/main.tex" \
    --out "$example_dir/jcp_submission" \
    --opened_macro rev \
    --removed_macro authorcomment \
    --opened_env revblock

echo
echo "--- source/ (this is what gets uploaded) ---"
ls -1 "$example_dir/jcp_submission/source"
echo
echo "--- report.md ---"
cat "$example_dir/jcp_submission/report.md"
