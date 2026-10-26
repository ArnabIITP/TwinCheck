<div align="center">

# TwinCheck

### Differential testing for black-box software compatibility

**Give TwinCheck two implementations. It explores inputs, detects behavioral differences, shrinks stable failures, and exports evidence you can replay in CI.**

[![CI](https://img.shields.io/github/actions/workflow/status/ArnabIITP/TwinCheck/ci.yml?branch=main&label=CI)](https://github.com/ArnabIITP/TwinCheck/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/ArnabIITP/TwinCheck?style=social)](https://github.com/ArnabIITP/TwinCheck/stargazers)
[![Forks](https://img.shields.io/github/forks/ArnabIITP/TwinCheck?style=social)](https://github.com/ArnabIITP/TwinCheck/network/members)
[![Issues](https://img.shields.io/github/issues/ArnabIITP/TwinCheck)](https://github.com/ArnabIITP/TwinCheck/issues)
[![Last commit](https://img.shields.io/github/last-commit/ArnabIITP/TwinCheck)](https://github.com/ArnabIITP/TwinCheck/commits/main)
[![License](https://img.shields.io/github/license/ArnabIITP/TwinCheck)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

</div>

> **Project status: early alpha.** TwinCheck is an actively developed prototype, not yet a mature general-purpose fuzzing platform, not a security sandbox, and not a proof of program equivalence. This repository is private during development. GitHub/third-party statistic badges may not resolve for private repositories; they query GitHub dynamically and are expected to become useful after the project is made public.

## Why TwinCheck exists

Replacing a parser, porting a tool to another language, implementing a compatible API, or migrating a data-processing library creates a difficult question: *does the replacement behave like the original on the inputs that matter?* Unit tests often cover expected examples but miss edge cases, error handling, formatting quirks, boundary values and differences in process behavior.

TwinCheck is intended to make those differences observable and actionable. Its initial target is a black-box command-line interface, so the reference and candidate may be implemented in different languages. It generates repeatable text inputs, runs both programs, compares their observable output and exit behavior, and records enough information to reproduce a finding.

The longer-term research direction is an **evidence-first compatibility lab**: structured input adapters, instability-aware comparisons, minimized counterexamples, portable regression artifacts, and eventually execution adapters for APIs and stateful protocols. AI-assisted input suggestions may be added later, but a model will never be treated as proof that a difference exists. A finding must be backed by actual executions.

## What is implemented today

| Capability | Current behavior |
| --- | --- |
| Deterministic input generation | Mixed, text, integer-boundary and JSON-shaped text strategies; seeded pseudo-random inputs |
| Known-corpus support | Reads UTF-8 files from a directory in stable path order, before generated cases |
| Black-box execution | Runs two commands without invoking a shell; supports stdin or a `{input}` argv placeholder |
| Observable comparison | stdout, stderr, exit code, timeout, output truncation and repeated-run instability |
| Output policy | Per-stream retained-byte cap; output is redirected to temporary files instead of unbounded in-memory pipes |
| Failure minimization | Bounded delta-debugging for stable mismatches; explicitly reports the trial budget |
| Reproduction | JSON reports retain the input and SHA-256 digest; `replay` re-runs a chosen finding with explicitly supplied commands |
| CI output | Human-readable summary, JSON evidence report, and JUnit XML with one testcase per tested input |
| Project quality | Standard-library tests, GitHub Actions CI, issue templates, MIT license and security/contribution policies |

This is a narrow foundation by design. It does not yet analyze arbitrary binaries, reconstruct protocols, observe filesystem/network side effects, perform coverage-guided instrumentation, or safely execute untrusted code.

## Quick start

Requires Python 3.11 or newer.

```bash
git clone https://github.com/ArnabIITP/TwinCheck.git
cd TwinCheck
python -m pip install -e .
```

Run the included example. The candidate deliberately mishandles some whitespace, so the command should find a difference and exit with status `1`.

```bash
twincheck compare \
  --reference "python examples/reference.py" \
  --candidate "python examples/candidate.py" \
  --strategy text \
  --cases 8 \
  --seed 7 \
  --minimize \
  --max-minimization-trials 8 \
  --output reports/demo.json \
  --junit reports/demo-junit.xml
```

The nonzero exit code is intentional: it makes a detected difference suitable for a CI gate. `reports/demo.json` contains the exact failing input and process evidence; JUnit XML is available to CI test-report parsers.

Run the tests locally:

```bash
python -m unittest discover -s tests -v
python -m twincheck --help
python -m twincheck compare --help
python -m twincheck replay --help
```

There are no runtime third-party dependencies. The packaging backend is a build-time dependency.

## How a comparison works

```mermaid
flowchart TD
    A[Seed + strategy + optional corpus] --> B[Unique UTF-8 input cases]
    B --> C[Run reference command]
    B --> D[Run candidate command]
    C --> E[Compare observable signatures]
    D --> E
    E --> F{Difference found?}
    F -- No --> G[Record case digest and continue]
    F -- Yes --> H[Record both observations]
    H --> I{Stable mismatch and minimization enabled?}
    I -- Yes --> J[Bounded delta debugging]
    I -- No --> K[Keep original input]
    J --> L[JSON + JUnit reports]
    K --> L
    G --> M[Final report]
    L --> M
```

Each finding is based on measured process behavior. A clean run means only that TwinCheck did not observe a difference in the cases it executed. It is never evidence that the programs are equivalent for all possible inputs.

## CLI guide

### Generate and compare cases

```bash
twincheck compare \
  --reference "python reference.py" \
  --candidate "python replacement.py" \
  --strategy mixed \
  --cases 500 \
  --seed 42 \
  --timeout 5 \
  --repeat 2 \
  --max-output-bytes 1000000 \
  --minimize \
  --output reports/compatibility.json \
  --junit reports/compatibility.xml
```

**Important options**

| Option | Meaning |
| --- | --- |
| `--cases N` | Maximum number of unique input cases; default `100` |
| `--seed N` | Seed for reproducible input generation; default `0` |
| `--strategy` | `mixed`, `text`, `integer`, or `json` |
| `--corpus DIR` | Try local UTF-8 corpus files before generated inputs |
| `--timeout SECONDS` | Per-target timeout; default `5` seconds |
| `--repeat N` | Run each target N times for each input to expose observable instability; default `1` |
| `--max-output-bytes N` | Retain at most N bytes per stdout/stderr stream; default `1,000,000` |
| `--minimize` | Try to shrink stable findings using delta debugging |
| `--max-minimize N` | Maximum findings to minimize; default `1` |
| `--max-minimization-trials N` | Maximum deletion trials per finding; default `30` |
| `--normalize-eol` | Compare CRLF, CR and LF as equivalent |
| `--ignore-trailing-whitespace` | Ignore spaces and tabs at line ends |
| `--ignore-stderr` | Exclude stderr from behavioral comparison |
| `--ignore-exit-code` | Exclude return code from comparison |
| `--output PATH` | Write full JSON evidence to a file |
| `--junit PATH` | Write JUnit XML for CI ingestion |
| `--format json` | Write JSON to stdout instead of the text summary |

### Input strategies

- **`text`** prioritizes empty input, whitespace, line endings, Unicode, control characters, long strings and random text.
- **`integer`** prioritizes signed integer boundaries, zero/sign variants and large numeric strings.
- **`json`** generates JSON-compatible scalars, arrays and nested objects as text. It does not yet validate inputs against a user-provided JSON Schema.
- **`mixed`** combines the known edge-case families and samples from each generator.

Known edge cases are attempted first. Generated values are deterministic for a given TwinCheck version, strategy, requested count and seed. Reproducibility across different future versions is not guaranteed unless the version is pinned.

### Pass input through stdin or argv

By default, the full input text is written to stdin. Commands are parsed into arguments and launched with `shell=False`.

```bash
# stdin: most general option
twincheck compare --reference "python ref.py" --candidate "python replacement.py" --cases 100

# argv substitution: useful for single-argument command-line tools
twincheck compare \
  --reference "python ref.py {input}" \
  --candidate "python replacement.py {input}" \
  --cases 100
```

If any command argument contains `{input}`, the token is replaced and stdin is empty. NUL characters and platform-specific argument restrictions may make some generated text unsuitable for argv; stdin is the preferred transport for such cases.

### Reuse a known corpus

Put UTF-8 input files in a directory. Files are recursively loaded in sorted path order, then de-duplicated. If the corpus has fewer entries than requested, generated inputs fill the remaining budget.

```bash
twincheck compare \
  --reference "python ref.py" \
  --candidate "python replacement.py" \
  --corpus tests/corpus \
  --cases 250
```

### Repeat runs and instability

`--repeat 3` executes both targets three times for each input. If a target's compared observable signature changes across its own runs, the finding includes `reference_unstable` or `candidate_unstable`. TwinCheck retains the per-run observations for findings where `repeat > 1`.

Repeated execution is a detector, not a cure for nondeterminism. Time, random seeds, concurrent services, locale, environment variables and external state may still influence behavior. If a target is unstable, rerun it with controlled dependencies before treating the cross-implementation mismatch as a deterministic regression.

### Replay a saved finding

A report may contain commands from a previous environment, but TwinCheck never executes those stored command strings automatically. Supply the commands explicitly when replaying an input.

```bash
twincheck replay \
  --report reports/compatibility.json \
  --finding 1 \
  --reference "python reference.py" \
  --candidate "python replacement.py" \
  --repeat 3 \
  --output reports/replay.json
```

The finding number is 1-based and refers to its position in the source report. Replay reports record the source report path and source input digest.

## Reports and exit codes

Each JSON report contains metadata, a per-case execution index with input SHA-256 and difference categories, detailed findings with exact input and process observations, timing, generator configuration, and limitations. `docs/report-schema-v1.schema.json` describes the report contract. The schema is versioned because reports are intended to become portable regression artifacts.

| Exit code | Meaning |
| ---: | --- |
| `0` | No differences found in tested cases |
| `1` | One or more differences, instability indicators, or incomplete-output observations found |
| `2` | Invalid arguments/input/report or a command could not be started |
| `130` | Interrupted by the user |

A JUnit report emits one testcase per executed input. It includes hashes and categories in failure detail rather than writing raw test inputs into CI logs. Keep the JSON report as the evidence artifact. Inputs can contain secrets, personal data or proprietary content, so review report artifacts before uploading or sharing them.

## Safety and correctness boundaries

- TwinCheck does **not** invoke a shell, but a command executable can still perform arbitrary actions with your operating-system permissions.
- This is not a sandbox. Run only commands you trust. Do not expose TwinCheck as a service that executes user-supplied commands.
- Output is redirected to temporary files and read back with a per-stream retention cap. When the cap is exceeded, the runner flags the observation and attempts to stop the target; a very fast process can finish before the next poll tick, so the file may briefly exceed the configured cap.
- A timeout is not a complete resource policy. CPU, memory, disk access, network access, filesystem changes and OS-specific spawned-process behavior are not fully isolated.
- Captured output is decoded as UTF-8 with replacement for invalid sequences; it is not byte-exact binary comparison.
- Timing is recorded for diagnosis but not used as a difference by default because timing noise can create false positives.
- The minimizer is bounded delta debugging. It seeks a smaller input preserving the observed mismatch categories; it does not guarantee a globally minimal counterexample.
- For unstable targets or truncated outputs, a finding may require manual revalidation.

See [Threat Model](docs/threat-model.md), [Architecture](docs/architecture.md), and [Design Decisions](docs/design-decisions.md).

## Project direction

TwinCheck is not trying to be a generic wrapper around an LLM. Its long-term hypothesis is that compatibility investigations become more useful when every claim is backed by reproducible executions and a portable counterexample. Areas for future work are sequenced in the [project plan](docs/project-plan.md) and [roadmap](docs/roadmap.md): schema-aware generation, richer normalized traces, API/protocol adapters, regression bundles, and an independently reviewed isolated-execution backend.

### Roadmap summary

| Stage | Goal | Status |
| --- | --- | --- |
| v0.1 | Deterministic CLI differential testing, minimization, JSON report, tests and CI | Prototype implemented |
| v0.2 | Replay workflow, JUnit output, repeated-run instability detection and bounded capture | Implemented in current development branch; needs broader cross-platform CI validation |
| v0.3 | Schema-aware input generation, adapters and stronger report contracts | Planned |
| v0.4 | Isolated execution and richer filesystem/network observations | Planned, security-sensitive |
| v1.0 | Stable APIs, benchmark corpus and trusted compatibility workflow | Not yet close to complete |

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m twincheck --help
```

A small end-to-end smoke benchmark is documented under [`benchmarks/`](benchmarks/README.md). Benchmark results must be published with the Python version, operating system, number of cases, rounds, and exact commands. A result from one machine is not a general performance claim.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Favor focused changes with reproducible tests. Do not commit real secrets, private production inputs, customer data or proprietary software captures.

## License

MIT. See [LICENSE](LICENSE).
