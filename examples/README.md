# Examples

These two scripts form a tiny, intentionally imperfect demonstration. `reference.py`
uses Python's full whitespace-aware `str.strip()`. `candidate.py` strips ordinary
spaces only, so tabs and line breaks can produce different outputs.

Run from the repository root after installing TwinCheck:

```bash
python -m pip install -e .
twincheck compare \
  --reference "python examples/reference.py" \
  --candidate "python examples/candidate.py" \
  --strategy text --cases 25 --seed 7 --minimize \
  --output reports/demo.json
```

A finding is expected. The CLI exits with status `1` when differences are found;
that is useful in CI and is not a tool failure. The example candidate is deliberately
buggy and must not be treated as a real implementation.
