# Benchmarks

TwinCheck includes a smoke benchmark for end-to-end process orchestration. It is intended to catch large accidental regressions and give developers a reproducible local baseline, not to claim superiority over mature fuzzers.

Run from the repository root:

```bash
PYTHONPATH=src python benchmarks/run_smoke.py --cases 10 --rounds 3
```

The benchmark compares two identity commands, repeats each round, and prints JSON containing Python version, platform, case count, rounds, individual elapsed times and cases per second. The end-to-end rate includes target process startup and temporary-file I/O.

When sharing a result, include the exact command, commit SHA, operating system/version, Python version, case count, seed, round count, and whether the machine was otherwise idle. Do not put a number in the main README without a reproducible method and multiple comparable runs. No benchmark result is checked into this repository as a universal performance claim.
