# competent_formatting — agent guide

`competent_formatting` builds **LaTeX tables** (and helps with figures) from Python data, with
careful number formatting and phantom-based column alignment, and ships `cf_view`, a local web
viewer that recompiles LaTeX documents on demand. This file documents the three areas most often
touched: the **number/float formatters**, the **table-making tools**, and the **viewer**.

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
