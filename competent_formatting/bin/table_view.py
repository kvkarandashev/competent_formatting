import os
import shutil
import subprocess

import click

from ..str_formatting import replace_special_LaTeX_symbols

pdflatex_command = "pdflatex"


def wrap_table_into_test_tex(table_source_file, pdf_title, newcommands=""):
    test_source = (
        """
\\documentclass[journal=jctc,manuscript=article,layout=traditional]{achemso}
\\usepackage{multirow,tabularx}
\\usepackage{booktabs}

"""
        + newcommands
        + """

\\title{"""
        + pdf_title
        + """}

\\begin{document}
\\maketitle

\\begin{table}
\\input{"""
        + table_source_file[:-4]
        + """}
\\end{table}
\\end{document}

"""
    )
    return test_source


@click.command()
@click.argument("filename")
@click.option(
    "--replacements",
    default=None,
    help="specifying comma-separated replacement string (e.g. 'a:\\mathrm{A},b:\\mathrm{B}') will result in the corresponding replacements being performed in the final PDF via addition of '\\newcommand' lines",
)
def main(filename, replacements):
    """
    Generate a PDF embedding the table created with `competent_formatting.tables` output, with `FILENAME` defining input TeX file.
    """
    if not (len(filename) > 4 and (filename[:-4] != ".tex")):
        print("Tex filename must end with '.tex'!")
        exit(1)

    if shutil.which(pdflatex_command) is None:
        print(f"{pdflatex_command} should be installed!")
        exit(1)

    newcommands = ""
    if replacements is not None:
        for replacement in replacements.split(","):
            r1, r2 = replacement.split(":")
            newcommands += "\\newcommand{" + r1 + "}{" + r2 + "}\n"

    pdf_title = "Displaying table: " + replace_special_LaTeX_symbols(filename)
    test_source = wrap_table_into_test_tex(filename, pdf_title, newcommands=newcommands)
    test_source_filename = "test_table_" + os.path.basename(filename)
    with open(test_source_filename, "w") as f:
        f.write(test_source)
    subprocess.run(["pdflatex", test_source_filename])
