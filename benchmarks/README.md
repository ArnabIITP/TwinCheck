# Benchmarks

TwinCheck includes a smoke benchmark for end-to-end process orchestration. It is intended to catch large accidental regressions and give developers a reproducible local baseline, not to claim superiority over mature fuzzers.

Run from the repository root:

```bash
PYTHONPATH=src python benchmarks/run_smoke.py --cases 10 --rounds 3
```

The benchmark compares two identity commands, repeats each round, and prints JSON containing Python version, platform, case count, rounds, individual elapsed times and cases per second. The end-to-end rate includes target process startup and temporary-file I/O.

When sharing a result, include the exact command, commit SHA, operating system/version, Python version, case count, seed, round count, and whether the machine was otherwise idle. Do not put a number in the main README without a reproducible method and multiple comparable runs. No benchmark result is checked into this repository as a universal performance claim.


## Stateful regression corpus v2

The stateful corpus is a deterministic correctness gate, not a throughput benchmark or a comparison with other fuzzers. It includes five fixed scenarios: a volatile-ID control, response-value drift, a stateful read-ordering defect, an idempotency/retry defect, and a reset-health guard that must block a stale-state target.

Install the schema-validation extra and run the corpus from the repository root:

```bash
python -m pip install -e ".[test]"
python benchmarks/verify_stateful_corpus.py
```

The verifier checks SHA-256 pins for the sequences, contracts, service fixture, and schemas; validates schema structure; runs the expected cases; verifies safe response-difference pointers; confirms named-step mismatch preservation during minimization; exports and replays a regression pack; and proves a tampered pack is rejected. It writes JSON reports, the minimized workflow, the pack and a summary into a new `reports/stateful-corpus-v2/` directory. That output directory must not already exist; use `--output-dir` to choose a new one.

CI runs the same verifier on Linux for Python 3.11, 3.12 and 3.13, and on Windows for Python 3.11. Synthetic evidence is uploaded as a short-retention GitHub Actions artifact for each matrix job. The fixture does not represent production service behavior, and a reset-health assertion verifies only the explicit fields it names.
