pybabel extract -o ./pytsb.pot --sort-by-file --msgid-bugs-address=m.vyskoc@seznam.cz --project=PyTSB --version="0.1" --no-wrap  ./../ 

pybabel update -d ./ -i ./pytsb.pot -D pytsb --ignore-obsolete

