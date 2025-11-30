from competent_formatting.tables import MultiColumn, MultiRow, latex_table, phantom

headers1 = [
    MultiRow("name", 2),
    phantom,
    MultiColumn("apples", 2),
    phantom,
    MultiColumn("oranges", 2),
    MultiRow("mass-averaged", 2),
]

headers2 = [None, None, "$\FOURIER$", "$\LAPLACE$", None, "$\mininf$", "$\maxinf$", None]

entry1 = ["Ana", None, 0.7, 1.3, None, 2.6, 3.4, (-16.5, 5.1)]

entry2 = ["Bob", None, 1.5, -0.3, None, 1.4, 16.8, (0.1, 10.0)]

entry3 = ["Cole", None, -2.5, 15.4, None, 9.3, 7.5, 5.0]

table_string = latex_table(
    [headers1, headers2, entry1, entry2, entry3],
    midrule_positions=[2],
    cline_positions={1: [(3, 4), (6, 7)]},
)

open("test.tex", "w").write(table_string)
