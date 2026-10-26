# Architecture

## Goal

TwinCheck is a local differential-testing engine for command-line programs. Given a reference command, a candidate command and a reproducible set of UTF-8 inputs, it runs both implementations and reports differences in observable behavior.

## Components

- `generators.py`: deterministic strategy implementations and UTF-8 corpus loader.
- `runner.py`: shell-free command parsing, process execution, timeouts and normalized observations.
- `compare.py`: comparison policy and bounded delta-debugging minimizer.
- `engine.py`: orchestrates input selection, execution, optional minimization and report construction.
- `report.py`: JSON serialization and terminal summary.
- `cli.py`: argument validation, output formatting and exit codes.

The dependencies point inward: the CLI calls the engine; the engine uses generators, the runner and comparison logic. The runtime intentionally uses only the Python standard library.

## Finding model

A finding includes the input text, SHA-256 digest of its UTF-8 representation, difference categories, reference and candidate observations, and minimization metadata. Each observation records exit code (or `null` after a timeout), stdout, stderr, timeout status and measured duration. Duration is recorded for diagnosis but is not compared as a behavioral mismatch because normal scheduling noise would create false positives.

## Execution contract

Commands are parsed with `shlex.split` and executed with `shell=False`. The default input channel is stdin. If a command argument includes `{input}`, TwinCheck substitutes the full case into that argument and sends no text on stdin. Commands run with the caller's permissions and optional shared working directory. The timeout is applied independently to each process.

## Determinism

Known edge cases are in a stable order. Pseudo-random generation uses a local `random.Random(seed)` instance rather than process-global random state. Corpus files are sorted by path before reading. Reports include strategy, seed, tool version and exact commands. Program-level nondeterminism is not controlled by the current engine.

## Comparison policy

By default, a difference in timeout status, exit code, stdout or stderr creates a finding. A compatibility contract may select JSON-semantic comparison for stdout/stderr and declare JSON Pointer paths to ignore. JSON object key order and insignificant whitespace do not matter in JSON mode; array order remains significant; malformed JSON is always a finding. The normalized contract and its SHA-256 fingerprint are included in every report. Text output normalization remains opt-in. `--ignore-stderr` and `--ignore-exit-code` should only be used when those observations are not part of the compatibility contract being tested.

## Minimization

The delta-debugging routine repeatedly attempts to delete input chunks while preserving the exact set of discrepancy categories found in the original case. This makes the report more informative than a raw fuzz case, but is bounded by a trial budget and is not a guarantee of a globally minimal string. Minimization re-runs both programs and can be expensive; a configurable number of findings are minimized.

## Future extension seams

1. Input adapters that produce structured values (JSON Schema, protocol messages, API request templates).
2. Observers for filesystem effects, network interactions, and structured traces.
3. Isolated execution backends (container or OS sandbox) for untrusted code.
4. Coverage feedback and grammar-aware generation.
5. Optional agent suggestions for new inputs, each validated by actual execution.
6. Report export to JUnit/SARIF and direct regression-test generation.

Schema-driven input generation, protocol/API adapters, coverage feedback and isolated execution remain roadmap items, not implemented capabilities in the current v0.2.0 alpha.
