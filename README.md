<div align="center">

# TwinCheck

**Find behavioral differences between two programs. Shrink them to a small reproducer. Keep the bug from coming back.**

A deterministic, dependency-free differential-testing CLI for command-line programs.

</div>

> **Status:** early prototype (v0.1.0). Useful for experiments and regression discovery; not a proof of equivalence or a security sandbox.

## Why TwinCheck?

When replacing a library, porting a tool to another language, changing a parser, or migrating a service, ordinary tests can miss edge cases. TwinCheck sends the same generated input to a reference program and a candidate program, compares their observable behavior, and reports discrepancies with a reproducible input. It can use delta debugging to shrink a failing input while preserving the same difference categories.

TwinCheck currently compares command-line programs by **stdout, stderr, exit code, and timeout behavior**. It is local-first, deterministic for a seed, and has no runtime dependencies.

## 60-second demo

Requires Python 3.11 or newer.

```bash
git clone https://github.com/ArnabIITP/twincheck.git
cd twincheck
python -m pip install -e .

twincheck compare \
  --reference "python examples/reference.py" \
  --candidate "python examples/candidate.py" \
  --strategy text \
  --cases 8 \
  --seed 7 \
  --minimize \
  --max-minimize 1 \
  --max-minimization-trials 8 \
  --output reports/demo.json
```

The included candidate deliberately contains a whitespace-handling bug, so this demo should find differences. The command exits with `1` when it finds differences; this is intentional so CI can fail on regressions.

After an editable install, `python -m twincheck --help` also works.

## How it works

```text
seed + strategy + optional corpus
              |
              v
       deterministic inputs
              |
      +-------+-------+
      |               |
      v               v
 reference program  candidate program
      |               |
      +-------+-------+
              v
 compare stdout / stderr / exit / timeout
              |
       discrepancy found?
              |
       +------+------+
       |             |
      no            yes
       |             |
   next input    optional delta-debugging
                     |
                     v
             JSON report + reproducer
```

## Quick usage

```bash
twincheck compare \
  --reference "python reference.py" \
  --candidate "python replacement.py" \
  --strategy mixed \
  --cases 500 \
  --seed 42 \
  --timeout 1.5 \
  --minimize \
  --max-minimize 1 \
  --max-minimization-trials 30 \
  --output reports/compatibility.json
```

### Input strategies

| Strategy | What it tries |
|---|---|
| `mixed` | Text, JSON-shaped data, and integer-like edge cases |
| `text` | Empty input, whitespace, newlines, Unicode, control characters, long text, seeded random strings |
| `integer` | Signed integer boundaries, large values, zero/sign variants, seeded random integers |
| `json` | JSON scalars, arrays, nested objects, boundary numbers, seeded random JSON values |

Known edge cases are tried first. Remaining inputs are generated with Python's seeded pseudo-random generator. The same version, strategy, case count and seed give reproducible inputs.

### Passing input to your program

By default, each case is sent to the program on **stdin**. TwinCheck does not invoke a shell; commands are parsed into arguments.

```bash
# stdin-based command
twincheck compare --reference "python ref.py" --candidate "python new.py" --cases 100

# For tools that accept the input as one command-line argument
twincheck compare \
  --reference "python ref.py {input}" \
  --candidate "python new.py {input}" \
  --cases 100
```

The `{input}` placeholder is replaced inside any command argument and, when used, stdin is left empty. Use it only when the target's interface expects a single text argument. Newlines and NUL characters may not be valid command-line arguments on all operating systems; stdin is more general.

### Reusing a known corpus

Place UTF-8 input files in a directory and pass `--corpus`. Files are tried in stable path order before generated inputs, up to `--cases` total inputs.

```bash
twincheck compare \
  --reference "python ref.py" \
  --candidate "python new.py" \
  --corpus tests/corpus \
  --cases 250
```

### Comparison controls

- `--normalize-eol`: treat CRLF, CR and LF as equivalent in outputs.
- `--ignore-trailing-whitespace`: ignore spaces and tabs at the end of output lines.
- `--ignore-stderr`: ignore stderr differences.
- `--ignore-exit-code`: ignore exit status differences.
- `--timeout SECONDS`: per-program timeout, default `2` seconds.
- `--minimize`: try to shrink the first finding while preserving its difference categories. To control runtime, the default budget is one finding and 30 trials; tune with `--max-minimize` and `--max-minimization-trials`.
- `--format json`: write the full report to stdout. `--output PATH` writes a report file regardless of console format.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | No differences found in the tested inputs |
| `1` | One or more behavioral differences found |
| `2` | Invalid arguments, invalid corpus, or a command could not be run |
| `130` | Interrupted by the user |

A successful run is not proof of equivalence: it says only that TwinCheck did not find a difference in the inputs it tested.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m twincheck --help
python -m twincheck compare --help
```

The runtime has no third-party dependencies. Tests use the Python standard library.

## Design principles

1. **Evidence over explanation.** Every finding stores the input and both process observations; an AI explanation can be added later but cannot replace evidence.
2. **Reproducibility by default.** Seeded input generation and serial JSON reports make results easy to repeat and diff.
3. **AI optional, not on the critical path.** Core testing should work offline without an API key.
4. **Never claim proof from sampling.** Passing means no difference was observed in the tested cases, not that the implementations are equivalent.
5. **Make the first useful capability excellent.** The initial target is command-line behavioral comparison before expanding to protocols, APIs or dynamic traces.

## Current limits

- Inputs are UTF-8 text, not arbitrary binary blobs.
- Programs run with the current user's permissions; TwinCheck is **not** a sandbox. Only execute trusted programs.
- Subprocess output is captured in memory; do not point it at an untrusted program that could emit unbounded output.
- Only observable command-line behavior is compared. Filesystem, network, timing, nondeterministic output, environment and hidden state are not modeled.
- The minimizer is a bounded delta-debugging heuristic. It aims for a small reproducer, not a proof of global minimality.
- Generated inputs are general-purpose; meaningful structured fuzzing will require adapters or schemas for the target domain.

See the [project plan](docs/project-plan.md), [architecture notes](docs/architecture.md), [roadmap](docs/roadmap.md), [contribution guide](CONTRIBUTING.md), and [GitHub setup guide](GITHUB_SETUP.md).

## Contributing

Bug reports, test cases, adapters and documentation improvements are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Please do not commit real secrets, proprietary inputs, personal data or sensitive production logs.

## License

MIT. See [LICENSE](LICENSE).
