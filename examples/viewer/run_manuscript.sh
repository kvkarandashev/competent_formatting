#!/bin/bash
# Set up (or recover) a .cf_view session for a manuscript directory holding a
# main text and an SI:
#
#   ./run_manuscript.sh ~/qmlcode/paper_manuscripts/2026_09_msorf main sd
#
# Once the session exists, you never need this script again: just run `cf_view`
# from the manuscript directory, or any subdirectory of it.
set -euo pipefail
manuscript=${1:?usage: run_manuscript.sh MANUSCRIPT_DIR [MAIN_STEM] [SI_STEM]}
main_stem=${2:-main}
si_stem=${3:-sd}

cd "${manuscript}"
cf_view \
    --doc "main=${main_stem}.tex" \
    --doc "si=${si_stem}.tex" \
    --opened_macro revised \
    --removed_macro collaboratorcomment \
    --open
