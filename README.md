# json2dir-taxi

json2dir in [Taxi](https://bigzaphod.github.io/Taxi/), the esolang where a program drives a
taxi around Townsburg. The whole evaluator — strict UTF-8 check, strict JSON parse,
validation and shell-script generation — is one Taxi program (`json2dir.taxi`), compiled from
a small readable stack-VM source (`gen/evaluator.py`) by a Python assembler
(`gen/taxivm.py`, `gen/taximap.py`) that computes legal routes on the real map and keeps the
taxi fuelled by carrying a paying "coin" passenger. A POSIX sh launcher frames stdin as one
decimal byte per line (the Post Office reads lines) and runs the generated shell script.

```sh
JSON2DIR_TAXI=/path/to/taxi ./json2dir < file.json
```

Regenerate: `python3 gen/evaluator.py > json2dir.taxi`
