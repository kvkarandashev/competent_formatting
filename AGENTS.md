# competent_formatting — agent guide

`competent_formatting` builds **LaTeX tables** (and helps with figures) from Python data, with
careful number formatting and phantom-based column alignment. This file documents the two areas
most often touched: the **number/float formatters** and the **table-making tools**.

## Dev workflow (read first)

- The package is installed normally (a copy in site-packages), **not** editable. After editing
  the source you must reinstall for the installed package to change: `make install`
  (`pip install .`). To test the source *without* reinstalling, run with
  `PYTHONPATH=<repo_root>` so `import competent_formatting` resolves to the source tree.
- Formatting/linting is via **pre-commit**: `make review` (= `pre-commit run --all-files`) runs
  `pyproject-fmt`, `black -l 99`, `isort` (black profile, width 99), `autoflake`, `flake8`. Run it
  before committing. Commit messages follow **Conventional Commits** (`feat:`, `fix:`, `build:`,
  `chore:` …) — `conventional-pre-commit` is configured.
- Tests: `make test` (`pytest ./tests/*`). `pyproject.toml` requires Python >= 3.12 (the Python
  classifiers are derived from `requires-python` by `pyproject-fmt` — don't edit them by hand).

## `number_formatting/` layout & dependency rule

Split by concern; the import graph is **acyclic** (`base` is the root, `utils` is a leaf):

- `base.py` — base class + shared LaTeX rendering primitives: `LaTeXNumber`, `inline_formula`,
  `pm_error`, `padded_number_string` (+ `pzero`, `pminus`). Imports only `..str_formatting`.
- `float_formats.py` — `LaTeXFloat`, `LaTeXScientific`, `LaTeXPlainFloat`, the `FloatWError` type
  and its predicates `isfloatwerr`/`get_floatwerror_mean`, plus float-only string helpers
  (`error_roundup`, `shift_decimal`, `brackets_enclosure`). Imports `base` + `str_formatting`.
- `integer_formats.py` — `LaTeXInteger`. Imports `base`.
- `reported_float_formats.py` — `ReportedFloat`, `LaTeXReportedFloat`, `is_reported_float`,
  `fraction_decimals`, `phantom_pad_fraction`, `update_reported_float_alignment_kwargs`. Imports
  `base` + `str_formatting`.
- `utils.py` — generic numeric predicates only: `isfloat`, `isint`, `int_numeral_length`. numpy
  only, no sibling imports.

`number_formatting/__init__.py` re-exports the public names; external code (`tables.py`, `json.py`,
downstream scripts) imports from `competent_formatting.number_formatting` and is insulated from
which submodule a symbol lives in.

## Formatters

All formatters subclass `LaTeXNumber`; calling an instance on a value returns a LaTeX string
(`$...$`). A **string** value is returned unchanged (so pre-formatted cells pass through verbatim).
Each formatter owns its rendering inside `get_formatted_*` methods (don't add parallel free
functions for rendering).

- **`LaTeXScientific(num_numerals=2)`** — scientific notation, e.g. `$(1.76\pm0.02){ \cdot }
  10^{1}$` (uses `\cdot`, not `\times`). Aligns exponents/signs with phantoms.
- **`LaTeXPlainFloat(num_decimals=2)`** — fixed-decimal floats (rounds), decimal-point aligned via
  left phantom padding.
- **`LaTeXInteger()`** — integers, optionally `\phantom{0}`-left-padded to a common width.
- **`FloatWError(mean_val, stat_err=None)`** — a float-with-error value. A `(mean, err)` tuple/list
  is equivalent. `stat_err=None` means "no error reported". In a column where *some* values carry
  errors (`werrs_present`), error-less values get a phantom `\pm <err>` so the `\pm` symbols stay
  aligned.

### `ReportedFloat` — preserve reported precision + phantom alignment

Use when literature/reported values have **heterogeneous precision** that must be shown verbatim
(e.g. `0.9`, `0.795`, `0.620`) while still aligning the column. `LaTeXPlainFloat` would round all to
a fixed decimal count; `ReportedFloat` keeps the digits and pads the *fractional part* with
`\phantom{0}` to the column's max.

```python
from competent_formatting.number_formatting import ReportedFloat
from competent_formatting.tables import latex_table

table = [
    ["method", "MAE"],
    ["A", ReportedFloat("0.9", "0.1")],   # -> $0.9\phantom{0}\phantom{0}\pm0.1\phantom{0}\phantom{0}$
    ["B", ReportedFloat("0.359", "0.063")],  # -> $0.359\pm0.063$   (already widest)
    ["C", ReportedFloat("0.7")],          # no error, column has errors ->
    ["D", "--"],                          #    $0.7\phantom{0}\phantom{0}\phantom{{}\pm0.000}$
]
latex_table(table, column_types="lc", midrule_positions=[1])
```

- `ReportedFloat(mean, err=None)` stores `mean`/`err` as **strings** (digits preserved).
- Alignment is handled by `latex_table`'s normal per-column pass — `update_reported_float_alignment_kwargs`
  accumulates `mean_decimals`, `err_decimals`, `werrs_present` for the column, then
  `LaTeXReportedFloat.get_formatted_number` renders each cell. **Do not** scan the column yourself.
- Helpers `fraction_decimals(s)` and `phantom_pad_fraction(s, n)` are reusable.

## Table-making tools (`tables.py`)

```python
latex_table(
    table,                       # list of rows (lists of cells)
    transposed=False,
    midrule_positions=[],        # row indices that get a \midrule prepended
    toprule=True, bottomrule=True,
    cline_positions={},
    float_formatter=LaTeXScientific(),
    int_formatter=LaTeXInteger(),
    reported_float_formatter=LaTeXReportedFloat(),
    column_types=None,           # e.g. "lcc"; emitted verbatim into \begin{tabular}{...}
    footnotes=None,              # a TableFootnotes instance (see below)
) -> str                         # a \begin{tabular}...\end{tabular} block
```

**Cell value types** (dispatched per cell):
- `None` → empty cell.
- `str` → emitted **verbatim** (no LaTeX escaping; a bare `\\` would break the row — use
  `cell_wlinebreaks` for line breaks).
- `float` / `np.float64` → `float_formatter`.
- `int` / `np.int64` → `int_formatter`.
- `(mean, err)` tuple / `list` / `FloatWError` → float-with-error via `float_formatter`.
- `ReportedFloat` → `reported_float_formatter`.
- `NumberWithFootnote(value, marker)` → wraps any numeric `value` (float, `(mean, err)`,
  `int`, `ReportedFloat`); renders it via the normal column alignment then appends `marker` as
  a superscript. Other numeric cells in the column reserve the marker width with a phantom (see
  Footnotes below).
- `MultiColumn(el, ncolumns=n)`, `MultiRow(el, nrows=n)` → spanning cells.

**How alignment works:** `latex_table` first scans every column (`update_alignment_kwargs`) to
accumulate per-column maxima (numeral widths, exponent widths, `werrs_present`, `mean_decimals`,
`err_decimals`), then renders each cell with those kwargs. To support a new value type, add a branch
to both `update_alignment_kwargs` and `latex_table_open_element_string` (as `ReportedFloat` does) —
do not pre-compute alignment outside the table.

**`column_types` caveat:** it is emitted verbatim and **not** validated against the actual number of
cells per row (only row-to-row width consistency is asserted). A wrong count (e.g. `"lcccc"` for a
3-column table) silently yields spurious empty columns.

**`cell_wlinebreaks(lines, vertical_alignment="t", horizontal_alignment="c")`** — the only correct
way to put line breaks inside a cell (nests a tabular).

### Footnotes (`TableFootnotes`)

```python
from competent_formatting.tables import TableFootnotes, latex_table

fn = TableFootnotes(footnote_type="multicolumn", check_footnote_repetition=True)
cell = name + fn.cell_marker(note_texts) + rest   # marker spliced into the cell, "" if no notes
...
latex_table(table, footnotes=fn)                  # renders the collected notes
```

- `footnote_type` (**default `"multicolumn"`**, needs no extra package):
  - `"multicolumn"` — notes appended as full-width `\multicolumn{N}{l}{...}` rows below
    `\bottomrule`; cell markers are superscripts `$^{a}$`.
  - `"threeparttable"` — wraps the tabular in `threeparttable`/`tablenotes`; cell markers are
    `\tnote{a}` (needs `\usepackage{threeparttable}`).
- `check_footnote_repetition=True` — identical note texts share one marker (deduped); `False` gives
  every occurrence its own marker.
- `cell_marker(notes)` registers one cell's note(s) (a string or list) and returns the marker to
  splice in (e.g. `\tnote{a}` or `$^{a,c}$`); markers are assigned `a, b, c, …` in first-appearance
  order (`alpha_footnote_marker`, handles >26 → `aa`). Build the table in final (e.g. date-sorted)
  order so markers read top-to-bottom.

**Footnote on a *number* cell** — for a marker on a numeric cell (not a text cell), wrap the value
in `NumberWithFootnote(value, marker)` where `marker = footnotes.cell_marker(text)`, and pass the
same `footnotes` to `latex_table`. The wrapped number keeps its column's numeric alignment and the
marker is appended after it (`$…$$^{a}$`); every other numeric cell in that column automatically
gets a `\phantom{$^{a}$}` so the numbers stay aligned. One marker width per column is assumed (the
widest is reserved if a column mixes markers). Call `cell_marker` while building rows top-to-bottom
so deduped markers read in order.
