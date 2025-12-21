#!/bin/bash

cf_macro_removal example.tex --removed_fields "firstauthorcomment:secondauthorcomment" --opened_fields "markingrevised" > processed_example.tex
