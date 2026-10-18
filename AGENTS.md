# competent_formatting — agent guide

`competent_formatting` builds **LaTeX tables** (and helps with figures) from Python data, with
careful number formatting and phantom-based column alignment, and ships three LaTeX tools:
`cf_quick_table_view`, which compiles one generated table on its own, `cf_view`, a local web
viewer that recompiles whole documents on demand, and `cf_jcp_source`, which turns a working
manuscript into a journal-ready source package. This file documents the areas most often
touched: the **number/float formatters**, the **table-making tools**, **rendering a table to
preview or width-check it**, the **source-processing layer**, the **submission packager**, and
the **viewer**.

## Dev workflow (read first)

- The package is installed normally (a copy in site-packages), **not** editable. After editing
  the source you must reinstall for the installed package to change: `make install`
  (`pip install .`). To test the source *without* reinstalling, run with
  `PYTHONPATH=<repo_root>` so `import competent_formatting` resolves to the source tree.
- The **viewer is an optional extra**: `pip install .` gives the table/formatting core only, while
  `pip install '.[view]'` adds fastapi, uvicorn, sse-starlette, pydantic and tomli-w. `make install`
  deliberately installs the core alone. Without the extra, `cf_view --help` still works but running
  it exits with instructions (see `import_viewer` in `bin/view.py`), and `tests/viewer/conftest.py`
  drops the viewer tests from collection so `make test` still passes.
- Formatting/linting is via **pre-commit**: `make review` (= `pre-commit run --all-files`) runs
  `pyproject-fmt`, `black -l 99`, `isort` (black profile, width 99), `autoflake`, `flake8`. Run it
  before committing. Commit messages follow **Conventional Commits** (`feat:`, `fix:`, `build:`,
  `chore:` …) — `conventional-pre-commit` is configured.
- Tests: `make test` (`pytest ./tests/*`). `pyproject.toml` requires Python >= 3.12 (the Python
  classifiers are derived from `requires-python` by `pyproject-fmt` — don't edit them by hand).

## `number_formatting/` layout & dependency rule

Split by concern; the import graph is **acyclic** (`base` is the root, `utils` is a leaf):

- `base.py` — base class + shared LaTeX rendering primitives: `LaTeXNumber`, `inline_formula`,
  `is_inline_formula`, `pm_error`, `padded_number_string` (+ `pzero`, `pminus`). Imports only
  `..str_formatting`.
- `float_formats.py` — `LaTeXFloat`, `LaTeXScientific`, `LaTeXPlainFloat`, the `FloatWError` type
  and its predicates `isfloatwerr`/`get_floatwerror_mean`, plus float-only string helpers
  (`error_roundup`, `shift_decimal`, `brackets_enclosure`). Imports `base` + `str_formatting`.
- `integer_formats.py` — `LaTeXInteger`. Imports `base`.
- `reported_float_formats.py` — `ReportedFloat`, `LaTeXReportedFloat`, `is_reported_float`,
  `fraction_decimals`, `phantom_pad_fraction`, `integer_numerals`, `phantom_pad_integer`,
  `update_reported_float_alignment_kwargs`. Imports `base` + `str_formatting`.
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
  accumulates `mean_decimals`, `err_decimals`, `werrs_present`, `mean_numerals` and `mean_minus`
  for the column, then `LaTeXReportedFloat.get_formatted_number` renders each cell. **Do not**
  scan the column yourself.
- Padding goes **both ways**, and both halves are needed for a column to line up on its decimal
  point: `phantom_pad_fraction` pads the fraction on the right (and reserves the decimal point
  itself for a value written without one, so `1` is as wide as `0.732`), while
  `phantom_pad_integer` pads the integer part on the left with `\phantom{0}` and reserves a
  `\phantom{-}` where the column holds a negative value. Without the left half a column mixing
  `-9.523` with `0.258` is centred cell by cell and its decimal points wander.
- Helpers `fraction_decimals(s)`, `phantom_pad_fraction(s, n)`, `integer_numerals(s)` and
  `phantom_pad_integer(s, n, minus_present=)` are reusable.

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
- `Styled(value, style=BOLD)` → wraps any cell so the rendered result is decorated;
  `MinInColumn` / `MaxInColumn` are the same thing decided per column (see **Marking a cell**).
- `MultiColumn(el, ncolumns=n)`, `MultiRow(el, nrows=n)` → spanning cells.

**How alignment works:** `latex_table` first scans every column (`update_alignment_kwargs`) to
accumulate per-column maxima (numeral widths, exponent widths, `werrs_present`, `mean_decimals`,
`err_decimals`, `mean_numerals`, `mean_minus`) plus anything else a cell has to know about its
column (`column_min`, `column_max`), then renders each cell with those kwargs. To support a new
value type, add a branch to both `update_alignment_kwargs` and `latex_table_open_element_string`
(as `ReportedFloat` does) — do not pre-compute alignment outside the table.

**`column_types` caveat:** it is emitted verbatim and **not** validated against the actual number of
cells per row (only row-to-row width consistency is asserted). A wrong count (e.g. `"lcccc"` for a
3-column table) silently yields spurious empty columns.

**`cell_wlinebreaks(lines, vertical_alignment="t", horizontal_alignment="c")`** — the only correct
way to put line breaks inside a cell (nests a tabular).

### Marking a cell — bold the best value in a column

```python
from competent_formatting.tables import BOLD, MinInColumn, Styled, latex_table

table = [
    ["method", "MAE", "RMSE"],
    ["A", MinInColumn((0.144, 0.004)), MinInColumn((0.207, 0.017))],   # -> {\boldmath$...$}
    ["B", MinInColumn((0.176, 0.015)), MinInColumn((0.246, 0.026))],
    ["note", Styled("see text"), None],                                 # -> \textbf{see text}
]
```

- **`CellStyle(text=(prefix, suffix), math=(prefix, suffix))`** — how a cell is set apart, as
  LaTeX. Two wrappers, because `\textbf{$0.144$}` **does not bold the digits** and does not say
  so: the math font is selected independently of the text font. `apply` picks by looking at the
  rendered cell, so callers pass a style and never ask which kind of cell they are on.
  Shipped: **`BOLD`** (`\textbf{…}` / `{\boldmath…}` — plain LaTeX, needs no package, and bolds
  the minus sign and the `\pm` too, which `\mathbf` would leave at normal weight) and
  **`UNDERLINE`**.
- **`Styled(value, style=BOLD)`** — unconditional; the caller decided.
- **`MinInColumn(value, style=BOLD, precision=None)` / `MaxInColumn(...)`** — decided during
  the per-column alignment pass, by comparing against *the other marked cells of the same
  column*. Only wrapped cells take part, so a column that mixes an error with a count compares
  neither against the other; **ties are all marked**, because a tie is what the numbers say.
  Pass `precision=<the column's decimals>`: the comparison is then made on the digits the cell
  prints, so two cells that both read `0.304` are either both marked or neither is. Without it
  the raw values decide and the table marks a difference it does not show.
- The wrapped value flows through its column's normal alignment first, so a marked number keeps
  its padding and its footnote marker and only then gets the wrapper. It works on any numeric
  cell type (`float`, `(mean, err)`, `int`, `ReportedFloat`, `NumberWithFootnote`) and on strings.
- `cell_numeric_key(cell)` is what the comparison uses — a float-with-error reduces to its mean,
  a `ReportedFloat` to its reported mean, a wrapper to what it wraps. A non-numeric cell raises
  rather than being silently skipped.
- Caveat worth knowing: **bold costs width**. A bold glyph is wider than its regular
  counterpart, so marking one cell widens its whole column — measured at 20pt on a six-column
  table of errors, which is enough to push a table that fitted over its float. `UNDERLINE` costs
  nothing: the rule takes exactly the width the cell already had. Either way, re-check a table
  near the edge with `check_table_fits`.

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
- `sort_cell_markers=True` (**default**) — a cell with several notes lists its markers in marker
  order (`$^{d,f}$`) regardless of the order the notes were passed in; sorting is by index, so
  `aa` follows `z`. A marker named twice in one cell is printed once. `False` keeps the order the
  notes were passed in.

**Footnote on a *number* cell** — for a marker on a numeric cell (not a text cell), wrap the value
in `NumberWithFootnote(value, marker)` where `marker = footnotes.cell_marker(text)`, and pass the
same `footnotes` to `latex_table`. The wrapped number keeps its column's numeric alignment and the
marker is appended after it (`$…$$^{a}$`); every other numeric cell in that column automatically
gets a `\phantom{$^{a}$}` so the numbers stay aligned. One marker width per column is assumed (the
widest is reserved if a column mixes markers). Call `cell_marker` while building rows top-to-bottom
so deduped markers read in order.

## `table_rendering.py` — previewing a table, and checking it fits

`latex_table` emits a bare `tabular`, which says nothing about how the table behaves inside a
real document. The thing that actually goes wrong is **width**: a table too wide for its float
is not a LaTeX error. LaTeX writes `Overfull \hbox (…pt too wide)` into the log, produces a PDF
anyway, and the table runs off the page. Nothing fails, nothing exits non-zero, and the problem
reaches the journal. This module exists to make that visible.

```python
from competent_formatting.table_rendering import render_table, check_table_fits

result = render_table("my_table.tex")                 # compiles in a temp dir, nothing kept
result.compiled          # did LaTeX succeed
result.fits              # did nothing run past the text width -- SEPARATE from compiled
result.worst_overfull_pt # how far over, in points
result.summary()         # "ok" | "123pt too wide" | the LaTeX errors

status, result = check_table_fits("my_table.tex")     # "ok" | "needs adjustbox" | "failed"
```

`compiled` and `fits` are deliberately separate properties. Collapsing them loses exactly the
case this is for: an over-wide table **compiles**.

`wrap_table_into_test_tex` builds the throwaway document and is parameterised, because the
width a table has to fit is a property of the *destination*, not of the table:

- `documentclass` — everything after `\documentclass`, options included. The default is the
  historical JCTC `achemso` preview; a RevTeX manuscript passes `[aip,jcp,preprint]{revtex4-2}`.
  Overflow figures are not transferable between classes (one table measured 130pt over in
  `achemso` and 40pt over in RevTeX `preprint`), so check against the real one.
- `packages` — `\usepackage` arguments. Given explicitly they **replace** the defaults.
- `preamble` — spliced in verbatim, for macro definitions and anything that is not a package line.
- `table_environment` — `table` (one column), `table*` (both), `sidewaystable` (rotated, needs
  `rotating`). A table that overflows `table` often fits `table*` untouched.
- `adjustbox` — wrap in `\begin{adjustbox}{max width=\textwidth,center}`, which shrinks an
  over-wide table to fit. `check_table_fits` tries this itself and reports `needs adjustbox`
  when it rescues the table, because that is a one-line manuscript change rather than a defect.

`render_table(path, out_dir=...)` keeps the wrapper document and the PDF there (the preview
case); without `out_dir` it works in a temporary directory that is removed, so only the parsed
result survives (the checking case) and no `test_table_*.tex`/`.aux`/`.log` litter is left
behind. A LaTeX failure is returned as a result, never raised; only a missing `pdflatex` raises
(`PDFLaTeXMissingError`).

### `cf_quick_table_view`

The CLI over the above — `competent_formatting/bin/table_view.py`, a thin wrapper as the other
`bin/` entry points are.

```bash
# Preview: writes test_table_<name>.pdf beside the table, as it always has.
cf_quick_table_view my_table.tex --replacements '\MAE:\mathrm{MAE}'

# Check against the manuscript's real class; exits non-zero if it does not fit.
cf_quick_table_view my_table.tex --check \
    --documentclass '[aip,jcp,preprint]{revtex4-2}' \
    --package booktabs --package multirow --table_environment 'table*'
```

Both modes report overfull boxes; the preview keeps its PDF and still exits 0, since looking at
a too-wide table is a legitimate thing to want. `--check` keeps nothing and gates on the result.
`--replacements` defines `\newcommand`s for macros the table uses but the test document would
not otherwise know (`--preamble_file` takes a whole file for the same purpose).

## `processing/` — reading and rewriting LaTeX source

Everything that treats a `.tex` file as *text to be rewritten* rather than a document to be
compiled. The import graph is acyclic and `latex_spans` is the root:

- `latex_spans.py` — the scanner that classifies every byte as **code**, **comment** or
  **protected** (verbatim-like). Every rewriter starts here, because the alternative is a
  regex that eventually eats a `%` inside a `\url`, inlines an `\input` that sits in a
  comment, or "normalises" a character inside `lstlisting`. Also `strip_comments_by_line`,
  which is line-preserving on purpose — a line is shortened or deleted, never joined — so
  provenance survives it.
- `macro_removal.py` — strips revision markup: `remove_macros(text, opened_fields=,
  removed_fields=, opened_envs=, removed_envs=)`. **Macros and environments both**, each
  either *opened* (markup goes, content stays) or *removed* (both go), with the
  `\newcommand`/`\newenvironment` that defines a stripped name dropped along with it.
- `flatten.py` — inlines `\input`/`\include` into one file **with provenance**: every output
  line knows the `(file, line)` it came from, through any depth of inclusion. Also finds and
  renames graphics.
- `unicode_ascii.py` — the non-ASCII → LaTeX table. Anything it does not cover is an error
  quoting the original file and line, never a silent pass-through.
- `latex_build.py` — running pdflatex/latexmk and parsing the log. Shared with
  `table_rendering.py` (overfull boxes) and `viewer/builds.py` (the build-status rule below),
  so there is one copy of each.
- `jcp_source.py` / `jcp_checks.py` — the submission packager and its checks (next section).

### Environments are first-class revision markup

`remove_macros` used to walk `LatexMacroNode`s only, so `\rev{...}` was stripped while
`\begin{revblock} ... \end{revblock}` sailed through untouched — including its
`\newenvironment` definition. Both forms are now handled, and the option appears in all three
places that strip markup:

| | macro | environment |
|---|---|---|
| `remove_macros` | `opened_fields` / `removed_fields` | `opened_envs` / `removed_envs` |
| `cf_macro_removal` | `--opened_fields` / `--removed_fields` (colon-separated) | `--opened_envs` / `--removed_envs` |
| `cf_view` | `--opened_macro` / `--removed_macro` | `--opened_env` / `--removed_env` |
| `cf_jcp_source` | `--opened_macro` / `--removed_macro` | `--opened_env` / `--removed_env` |

A macro and an environment can share a name and are stripped differently, so the viewer's
session config keys a transform on the **pair** (`kind`, name); `Transform` is a union
discriminated by `kind`, and a config written before environments existed still loads because
every transform in it says `kind = "strip_macro"`.

## `cf_jcp_source` — a submittable source package

```bash
cf_jcp_source main.tex --out jcp_submission \
    --si sm.tex \
    --opened_macro rev --opened_env revblock \
    --removed_macro authorcomment
```

Writes a directory holding what AIP's Peer X-Press upload wants:

```
jcp_submission/
├── source/          # flat: main.tex, fig1.pdf, ... (+ main.bbl with --bbl separate)
├── source.zip       # the same files, no folder inside the archive
├── main.pdf         # the author-generated PDF, built from source/ in isolation
├── sm.pdf           # with --si
├── alt_text.txt     # a draft, one entry per figure and table
├── report.md        # checks, figure map, replacements
└── build/           # the working builds, kept so a failure can be inspected
```

Pipeline: flatten `\input`s → strip revision markup → normalise non-ASCII → full `latexmk`
build (for the `.bbl` and a reference page count) → copy and rename figures → inline the
`.bbl` → ship local `.sty`/`.cls` → **verify** → supplementary material → alt text, archive,
report. Sources are never modified.

### The guarantee: verified in an empty directory, with pdflatex alone

The last step copies `source/` into a fresh directory and compiles it there with **pdflatex
only** — no latexmk, no BibTeX, no project `latexmkrc`, nothing else from the project. An
undefined reference, a missing file or a LaTeX error *there* is a hard failure, because it
would be a failure at the journal too. This is the whole point of the tool; a packager that
only copies files tells you nothing. The same build's page count is compared with the full
build's, because a difference means flattening changed the document.

Hard failures also include: a font not embedded in a PDF figure, a non-ASCII byte left in a
shipped `.tex`, a subdirectory in `source/`, and revision markup still present after cleaning.
Everything else (class options, duplicate packages, placeholders, missing Data Availability or
Author Declarations sections, overfull boxes, float citation order) is a warning — `--strict`
promotes them. Exit codes: 0 clean, 1 a hard check failed (output kept), 2 a usage error.

### Two things that are easy to get wrong

- **BibTeX runs more than once.** Under RevTeX a `\cite` inside a `\footnote` goes through a
  second database (`<stem>Notes.bib`) that does not exist until after the first BibTeX pass,
  so one pass leaves it undefined. `latexmk` is used for the full build precisely so the
  passes are repeated as often as needed; the `.bbl` it produces is what gets shipped.
- **The `.bbl` is spliced in literally.** It is dense with backslashes, and `re.sub` reads
  `\1` or `\g<0>` in a title as a replacement-group reference. `inline_bibliography` slices.

### What is not verifiable

AIP's public author instructions cover figures, alt text, the RevTeX template and the required
declarations. What they do **not** state is whether the Peer X-Press TeX pipeline runs BibTeX
or accepts subdirectories — that lives in a PXP FAQ that could not be fetched. The defaults
are therefore the ones that are correct under either answer: a flat directory and the
bibliography inlined from the `.bbl`, with `--bbl separate` as the alternative. If the FAQ is
ever consulted, only defaults need to change.

### `--force` does not mean "delete whatever is there"

It removes only the names this tool writes (`source/`, `build/`, `source.zip`, `*.pdf`,
`alt_text.txt`, `report.md`). A `--out` holding anything else is refused, so pointing the tool
at the wrong directory cannot destroy work. `--out` may also not be the manuscript directory
or a parent of it.

### EPS figures

AIP prefers EPS for accepted manuscripts, so an `.eps` is shipped as-is. pdflatex cannot read
it directly, so the isolated verification build converts it with `epstopdf` first (and warns
if `epstopdf` is missing). The shipped package is unaffected either way.

## `viewer/` — the `cf_view` web viewer

`cf_view` serves a browser UI (FastAPI + PDF.js) that displays one or more compiled `.tex`
documents and recompiles them on demand. It exists so a manuscript and its SI can be read
side-by-side with a "clean" variant that has revision markup stripped out.

```bash
pip install '.[view]'        # the viewer's dependencies are an optional extra

# One-time setup, run from the manuscript directory:
cf_view --doc main=main.tex --doc si=sd.tex \
        --opened_macro revised --removed_macro collaboratorcomment \
        --pre_script "python figures/make_all.py"

# From then on, from that directory or any subdirectory of it:
cf_view
```

### Session discovery (`.cf_view`)

With no `--workdir`, `cf_view` walks up from the current directory looking for a `.cf_view/`
holding a `competent_viewer.toml` — the way git finds `.git` — and uses the first one it finds.
Failing that it seeds a new session in `./.cf_view`. An explicit `--workdir` bypasses discovery
entirely, so the older `--workdir ./some-session` style still works.

Two consequences make a `.cf_view` directory safe to **commit alongside the manuscript**:

- **Document paths are stored relative to the workdir** when the document lives inside the project
  (`main_tex = "../main.tex"`), and absolute otherwise. The config is therefore portable: clone the
  manuscript somewhere else and the session still resolves. `save_config`/`load_config` convert at
  the boundary, so the in-memory model always holds absolute paths and nothing else has to care.
- **`save_config` writes a `.gitignore` into the session directory** (once, never overwritten)
  covering `build/`, `logs/` and the lock file, so only `competent_viewer.toml` is tracked.

`build_missing_on_start` (default true) makes the server compile anything whose PDF is absent as
soon as it starts, so a freshly cloned session shows documents instead of "not built yet". A
restart where `build/` is already populated rebuilds nothing and serves immediately — build
*statuses* are per-process, so the UI labels those PDFs `cached` rather than `not built`.

`examples/viewer/run_demo.sh` runs it against two small demo documents that actually contain
revision markup; `run_manuscript.sh` points it at a real manuscript directory.

### Module layout

- `defaults.py` — constants (`DEFAULT_LATEX_CMD`, profile names, the missing-extra hint), kept
  **free of third-party imports** so `bin/view.py` can read them without pulling in the extra.
  If you add a viewer constant that the CLI needs at import time, it belongs here, not in
  `config.py`.
- `config.py` — Pydantic models (`SessionConfig`, `Document`, `Profile`, `MacroTransform`,
  `Hook`) plus atomic TOML load/save. **The config file is the single source of truth**: the CLI
  seeds it, the browser menu mutates it, the server reads it. Nothing that must survive a restart
  lives only in memory.
- `session.py` — seeding a config from CLI flags and `reconcile()`-ing on restart.
- `transforms.py` — the source transform, a thin wrapper over
  `processing.macro_removal.remove_macros`.
- `builds.py` — copy → transform → compile, log capture, and the build-status rule.
- `worker.py` — a single background thread draining an ordered job queue, plus the SSE `EventBus`.
- `app.py` — FastAPI routes; `bin/view.py` is the thin `click` entry point.
- `static/` — the frontend. Shipped via `package-data` in `pyproject.toml`; if you add a file
  there, it is already covered by the `static/*` glob, but **you must `make install` for the
  installed copy to see it** (the usual non-editable-install gotcha).

### Profiles and macro semantics

Revision markup is expressed as **macros, not environments** — the only stripping machinery in the
package is `remove_macros`, which walks `pylatexenc` nodes looking for `LatexMacroNode`s.
Each declared macro maps onto one of its two existing field lists:

| CLI flag | `remove_macros` field | Effect |
|---|---|---|
| `--opened_macro revised` | `opened_fields` | `\revised{text}` → `text` (content kept) |
| `--removed_macro collaboratorcomment` | `removed_fields` | `\collaboratorcomment{x}` → `` (content dropped) |

All declared macros go into **one aggregate `clean` profile**, not one profile per macro, so the UI
stays a plain `full` ↔ `clean` toggle. `\newcommand` definitions of a stripped macro are dropped
too (`processed_command_definition` handles that), so the clean copy does not reference an
undefined macro.

Unwrapping does not change how much text there is, so `full` and `clean` stay aligned page for
page — which is what makes the toggle useful. Deleting a comment macro *does* reflow the text; that
is expected, and is why comment macros and revision macros are separate flags.

### Build-status rule — do not "simplify" this to the exit code

`latexmk` exits non-zero on a non-fatal BibTeX error (e.g. a `@misc` entry with no `title`) and
**re-reports that cached error on every subsequent no-op run**. The default compile command
therefore passes `-f`, and status is decided by whether the PDF is at least as new as the inputs it
was built from, not by the exit code:

| Condition | Status | Shown |
|---|---|---|
| no PDF at all | `failed` | previous PDF, if any |
| PDF older than the sources | `failed` | previous PDF |
| PDF current, exit code 0 | `ok` | new PDF |
| PDF current, exit code non-zero | `warning` | new PDF + a warning |

Keying off the exit code alone makes a perfectly good manuscript read as permanently broken;
keying off "a PDF exists" alone hides genuine failures behind a stale PDF.
`tests/viewer/test_viewer_builds.py` pins all four rows.

### Logs

Two logs per build, both at stable paths and both surfaced in the UI (the log panel prints the
filesystem paths so they can be opened in an editor):

- `<workdir>/logs/<doc_id>__<profile>.log` — the driver's combined stdout/stderr.
- `<workdir>/build/<doc_id>/<profile>/<stem>.log` — the **TeX log**. Diagnostics such as
  `LaTeX Warning: There were undefined references` live here and *not* in the driver output, so
  this is the one to grep when hunting compilation problems.

### Invariants worth preserving

- **Sources are never mutated.** Builds run on a copy in `<workdir>/build/<doc_id>/<profile>/`.
  `materialize_build_dir` writes a file only when its *content* changes, so untouched inputs keep
  their mtime and `latexmk` stays incremental (~0.1 s vs ~3 s for this repo's test manuscript).
- **A workdir nested inside the source tree is skipped** when copying, or a build would recurse
  into itself.
- **Compilation never blocks a request handler.** Routes enqueue; one worker thread compiles;
  progress reaches the browser over SSE.
- **Explicit-vs-default flag detection is required behavior**, not a detail:
  `click`'s `ctx.get_parameter_source(...) is ParameterSource.COMMANDLINE` drives reconciliation.
  On restart, an explicitly-passed flag that contradicts the persisted config exits 2 with a listing
  of `<flag>: CLI=<value> vs workdir=<value>`; `--overwrite_config` is the escape hatch. Flags left
  at their default never reset a stored value.

### Two caveats

- **PDF.js is loaded from cdnjs**, so the UI needs internet on first load. Vendor
  `pdf.min.js`/`pdf.worker.min.js` into `static/` if you need it to work offline.
- **The recompile button is remote code execution**: it runs the configured hooks. The default bind
  is `127.0.0.1`; prefer `tailscale serve` in front of a localhost bind over widening `--host`.
