import os
import subprocess
import sys

from ..str_formatting import replace_special_LaTeX_symbols


def wrap_table_into_test_tex(table_source, pdf_title):
    test_source = (
        """
\\documentclass[journal=jctc,manuscript=article,layout=traditional]{achemso}
\\usepackage{multirow,tabularx}
\\usepackage{booktabs}

\\title{"""
        + pdf_title
        + """}

\\begin{document}
\\maketitle

\\begin{table}
"""
        + table_source
        + """
\\end{table}
\\end{document}

"""
    )
    return test_source


def main():
    assert len(sys.argv) > 1, "Name of tex source should be the first argument"
    filename = sys.argv[1]
    pdf_title = "Displaying table: " + replace_special_LaTeX_symbols(filename)
    table_source = open(filename, "r").read()
    test_source = wrap_table_into_test_tex(table_source, pdf_title)
    test_source_filename = "test_table_" + os.path.basename(filename)
    with open(test_source_filename, "w") as f:
        f.write(test_source)
    subprocess.run(["pdflatex", test_source_filename])
