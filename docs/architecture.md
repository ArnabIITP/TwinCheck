# Architecture

## Goal

TwinCheck is a local differential-testing engine for command-line programs. Given a reference command, a candidate command and a reproducible set of UTF-8 inputs, it runs both implementations and reports differences in observable behavior.

## Components

- `generators.py`: deterministic strategy implementations and UTF-8 corpus loader.
- `runner.py`: shell-free command parsing, process execution, timeouts and normalized observations.
- `compare.py`: comparison policy and bounded delta-debugging minimizer.
- `engine.py`: orchestrates input selection, execution, optional minimization and report construction.
- `stateful_http.py`: local multi-request HTTP workflows, capture/reuse, independent sessions, optional reset-before-repeat, and replay evidence.
- `stateful_explore.py`: deterministic workflow mutation, response-feedback candidate prioritization, and bounded reset-backed step/body minimization.
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

By default, a difference in timeout status, exit code, stdout or stderr creates a finding. Output normalization is opt-in. `--ignore-stderr` and `--ignore-exit-code` should only be used when those observations are not part of the compatibility contract being tested.

## Minimization

The delta-debugging routine repeatedly attempts to delete input chunks while preserving the exact set of discrepancy categories found in the original case. This makes the report more informative than a raw fuzz case, but is bounded by a trial budget and is not a guarantee of a globally minimal string. Minimization re-runs both programs and can be expensive; a configurable number of findings are minimized.

## Future extension seams

1. Input adapters that produce structured values (JSON Schema, protocol messages, API request templates).
2. Observers for filesystem effects, network interactions, and structured traces.
3. Isolated execution backends (container or OS sandbox) for untrusted code.
4. Coverage feedback and grammar-aware generation.
5. Optional agent suggestions for new inputs, each validated by actual execution.
6. Report export to JUnit/SARIF and direct regression-test generation.

Structured inputs, local HTTP, stateful workflows and response-shape/transition feedback exist in the current alpha. The exploration scheduler ranks a bounded candidate pool; response fingerprints are not source-code coverage, and the service reset remains a trusted user-authored workflow. Container isolation, filesystem observation and instrumented service coverage remain future work. Value-level JSON body minimization is bounded and currently implemented as a greedy pass after step deletion.
