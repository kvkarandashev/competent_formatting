#!/bin/bash
# Launch cf_view on the two small demo documents in ./demo.
#
# The `clean` profile unwraps \revised{...} (keeping the text) and deletes
# \collaboratorcomment{...} outright; toggle between `full` and `clean` in the
# browser, or press "c".
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

cf_view \
    --workdir "${here}/demo-session" \
    --doc "main=${here}/demo/main.tex" \
    --doc "si=${here}/demo/si.tex" \
    --opened_macro revised \
    --removed_macro collaboratorcomment \
    --open
