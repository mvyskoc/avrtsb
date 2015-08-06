#!/bin/bash
pybabel extract -o ./pytsb.pot -k_l -k_ --sort-by-file --msgid-bugs-address=m.vyskoc@seznam.cz --project=PyTSB --version="0.2" --no-wrap  ./../ 

pybabel update -d ./ -i ./pytsb.pot -D pytsb --ignore-obsolete

