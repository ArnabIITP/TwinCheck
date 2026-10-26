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


## JSON compatibility contract

The following pair emits semantically equivalent JSON, although volatile metadata and key order differ:

```bash
python -m pip install -e .
twincheck compare \
  --reference "python examples/json_reference.py" \
  --candidate "python examples/json_candidate.py" \
  --strategy json --cases 12 --seed 17 \
  --contract examples/contracts/json-api-v1.json \
  --output reports/json-compatibility.json
```

The run should report no differences because the contract explicitly ignores `/request_id` and `/meta/generated_at`. Removing those paths should reveal the differences.

## Portable regression pack

After a finding has been reported, turn it into an input pack. The pack stores exact inputs and the contract but never stores executable commands to run:

```bash
twincheck export-pack --report reports/compatibility.json --output tests/twincheck-regressions
twincheck replay-pack --pack tests/twincheck-regressions \
  --reference "python reference.py" --candidate "python replacement.py"
```

Once the candidate is fixed, replay should return zero. A recurrence of a difference returns a non-zero status.
