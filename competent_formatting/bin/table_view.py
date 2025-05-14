import argparse
import os
import subprocess

from ..str_formatting import replace_special_LaTeX_symbols


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=str)
    parser.add_argument("--replacements", type=str)
    args = parser.parse_args()
    filename = args.filename

    if not (len(filename) > 4 and (filename[:-4] != ".tex")):
        print("Tex filename must end with '.tex'!")
        quit()

    newcommands = ""
    if args.replacements is not None:
        for replacement in args.replacements.split(","):
            r1, r2 = replacement.split(":")
            newcommands += "\\newcommand{" + r1 + "}{" + r2 + "}\n"

    pdf_title = "Displaying table: " + replace_special_LaTeX_symbols(filename)
    test_source = wrap_table_into_test_tex(filename, pdf_title, newcommands=newcommands)
    test_source_filename = "test_table_" + os.path.basename(filename)
    with open(test_source_filename, "w") as f:
        f.write(test_source)
    subprocess.run(["pdflatex", test_source_filename])
