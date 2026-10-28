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

## Synthetic exploration protocol v1

The dedicated exploration corpus is separate from the stateful regression gate. It contains four expected-outcome scenarios: a clean compatibility control, a response-value drift, a stateful read-ordering defect, and a two-field interaction defect designed to expose one known static/adaptive difference under a two-case budget.

Run the paired protocol from the repository root after installing the test extra:

```bash
python -m pip install -e ".[test]"
python benchmarks/run_exploration_protocol.py --rounds 2 --max-run-seconds 20 --output reports/exploration-protocol-v1.json
```

Before invoking the targets, the runner validates the manifest against [its versioned schema](exploration-corpus-v1.schema.json), verifies SHA-256 pins for every listed service, sequence, contract, schema and the protocol runner, and validates sequence/contract files with the project schemas and loaders. All targets bind to ephemeral loopback ports and use in-memory synthetic state.

Static and adaptive runs use the same per-case candidate budget and pinned seeds. The report includes each run's expected-outcome status, executed case count, named difference steps, mutation-schedule fingerprint, response-branch/transition counts, elapsed time, and paired results. Repeated runs must retain the same schedule and outcome. Sensitive request/response bodies are not copied into the summary. CI executes this protocol on Linux/Python 3.11–3.13 and Windows/Python 3.11 and stores the result alongside the existing stateful corpus evidence.

The paired-field interaction is a deliberately small test of a known adaptive candidate, not evidence that adaptive mode is generally more effective. The suite exercises one synthetic cart API; it does not cover production APIs, concurrency, distributed state, or every mutation strategy. Reported timings include local server lifecycle overhead and are diagnostic only. Do not use these numbers as general performance or superiority claims.

## Exploration scorecard v1

The paired exploration protocol can be summarized into a confusion-matrix scorecard:

```bash
python benchmarks/run_exploration_protocol.py --rounds 2 --max-run-seconds 20 --output reports/exploration-protocol-v1.json
python benchmarks/score_exploration_protocol.py --report reports/exploration-protocol-v1.json --output reports/exploration-scorecard-v1.json
```

Ground truth is assigned at the scenario level: if either pinned mode expectation says a scenario contains a defect, it is a seeded defect for both modes. Thus a defect missed by static exploration counts as a false negative instead of being reclassified as a clean control. Only scenarios where both modes are expected to report no finding count as clean controls. The scorecard refuses failed or incomplete protocol reports. Its detection, false-positive and precision figures describe only this tiny pinned synthetic corpus and are not estimates of real-world effectiveness.
