#!/bin/bash

python make_table.py

cf_quick_table_view --replacements "\FOURIER:\mathcal{F},\LAPLACE:\mathcal{L},\mininf:\mathrm{min}_{\inf},\maxinf:\mathrm{max}_{\inf}" test.tex
