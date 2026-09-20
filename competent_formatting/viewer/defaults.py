"""Constants shared by the viewer and its CLI.

Kept free of third-party imports so that ``cf_view`` can read them -- and print
a useful message -- when the optional ``view`` dependencies are absent.
"""

CONFIG_FILENAME = "competent_viewer.toml"
LOCK_FILENAME = ".competent_viewer.lock"

# Project-local session directory, discovered by walking up from the cwd the
# way git finds .git.  Holds the config plus regenerable build/ and logs/.
WORKDIR_DIRNAME = ".cf_view"

# ``-f`` keeps latexmk going through a non-fatal BibTeX error; without it a
# single bad .bib entry leaves every citation unresolved.  Build success is
# judged on whether the PDF is current, not on the exit code (see builds.py).
DEFAULT_LATEX_CMD = "latexmk -pdf -interaction=nonstopmode -f {main}"

FULL_PROFILE = "full"
CLEAN_PROFILE = "clean"

VIEW_EXTRA_HINT = (
    "cf_view needs the optional 'view' dependencies (fastapi, uvicorn, "
    "sse-starlette, pydantic, tomli-w).\n"
    "Install them with:  pip install 'competent-formatting[view]'\n"
    "or, from a checkout: pip install '.[view]'"
)
