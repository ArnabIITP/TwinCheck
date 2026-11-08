# TwinCheck quick start

This guide gets TwinCheck running from a source checkout and walks through command-line and local HTTP comparisons.

> TwinCheck is alpha software. Version `0.12.0a1` is published on [PyPI](https://pypi.org/project/twincheck/0.12.0a1/). Python 3.11 or newer is required.

## 1. Install the published alpha

Install the pinned pre-release:

```bash
python -m pip install --pre twincheck==0.12.0a1
```

Check that the command is available:

```bash
twincheck --help
```

If your environment does not expose installed scripts on PATH, check the Scripts directory for your Python installation or repair the PATH entry. The package provides the `twincheck` console command.

## 2. Install from source

The remaining walkthrough uses the repository's included examples, so clone the repository as well:


```bash
git clone https://github.com/ArnabIITP/TwinCheck.git
cd TwinCheck
python -m pip install -e .
```

Check that the CLI is available:

```bash
twincheck --help
```

If your environment does not expose installed scripts on PATH, use:

```bash
python -m twincheck --help
```

The core package has no runtime third-party dependencies. The optional `test` extra installs the JSON Schema validation dependency used by tests and benchmark tooling.

## 3. Compare two command-line implementations

The repository includes a reference program and a deliberately different candidate.

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

The candidate intentionally mishandles some whitespace. TwinCheck should detect a behavioral difference and return exit status `1`. This is expected for the demo. In CI, a nonzero exit status can fail the job when a difference is found.

The output files contain:
- `reports/demo.json`: machine-readable execution evidence and findings.
- `reports/demo-junit.xml`: JUnit XML for test-report integrations.

On Windows PowerShell, create the directory with:

```powershell
New-Item -ItemType Directory -Force reports
```

### Useful options

| Option | Description |
| --- | --- |
| `--cases N` | Maximum number of unique generated cases |
| `--seed N` | Seed for reproducible input generation |
| `--strategy` | `mixed`, `text`, `integer`, or `json` |
| `--corpus DIR` | Read known UTF-8 cases before generated inputs |
| `--schema PATH` | Generate inputs from the supported JSON Schema subset |
| `--timeout SECONDS` | Per-target timeout |
| `--repeat N` | Repeat cases to expose observable instability |
| `--max-output-bytes N` | Maximum retained bytes per stdout/stderr stream |
| `--minimize` | Attempt bounded minimization of stable findings |
| `--output PATH` | Write a JSON evidence report |
| `--junit PATH` | Write JUnit XML |

See all flags with:

```bash
twincheck compare --help
```

## 4. Compare two local HTTP implementations

Start two instances of the included quote service in separate terminals:

```bash
python examples/http_service.py --port 8001 --delta 0
python examples/http_service.py --port 8002 --delta 1
```

Run the comparison from a third terminal:

```bash
mkdir -p reports
twincheck compare-http \
  --reference-url http://127.0.0.1:8001 \
  --candidate-url http://127.0.0.1:8002 \
  --path /quotes \
  --method POST \
  --schema examples/schemas/quote-request-v1.json \
  --contract examples/contracts/http-api-v1.json \
  --cases 25 \
  --seed 42 \
  --output reports/http-compatibility.json \
  --junit reports/http-compatibility.xml
```

The candidate adds a delta to the calculated total, so the comparison should find a difference. Start both services with `--delta 0` to try the compatible control.

HTTP mode is restricted to loopback addresses (`localhost`, `127.0.0.1`, and `::1`). It is intended for local test services, not remote API scanning. TwinCheck does not start or sandbox the services.

## 5. Compare a stateful HTTP workflow

A single request may not expose a regression that appears only after a sequence of operations. The included cart example creates a cart, adds an item, and reads the resulting state.

Start two services:

```bash
python examples/stateful_cart_service.py --port 8001 --cart-id reference-cart
python examples/stateful_cart_service.py --port 8002 --cart-id candidate-cart --total-delta 1
```

Run the workflow:

```bash
twincheck compare-http-sequence \
  --reference-url http://127.0.0.1:8001 \
  --candidate-url http://127.0.0.1:8002 \
  --sequence examples/sequences/cart-create-add-read-v1.json \
  --contract examples/contracts/stateful-cart-v1.json \
  --output reports/cart-workflow.json \
  --junit reports/cart-workflow.xml
```

The workflow captures a value from the create response and uses it in later requests. The two services use different cart identifiers, while the contract ignores that volatile field and still compares the calculated total.

Stateful workflows can mutate service state. Use disposable local services and synthetic data. For exploration and replay, read the CLI help and the [stateful sequence format](stateful-http-sequence-v1.schema.json).

## 6. Run tests and validate a package build

Install the optional test dependency:

```bash
python -m pip install -e ".[test]"
```

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

Build and verify a wheel and source archive:

```bash
python -m pip install --upgrade build twine
python -m build --outdir dist
python scripts/verify_distribution.py --dist-dir dist
```

The distribution verifier checks package metadata and archive contents, installs the wheel into a clean environment outside the checkout, and exercises the installed CLI.

## 7. Interpret results carefully

- A reported mismatch is evidence of a difference under the executed inputs and configured comparison contract.
- A clean run means no difference was observed in the cases executed. It does not prove equivalence.
- Generated cases are seeded, but exact generation behavior may change between alpha versions. Pin the TwinCheck version for reproducible automation.
- Reports and replay packs may contain inputs and response observations. Review and sanitize them before sharing.
- TwinCheck launches configured commands with the current user's permissions. It is not a sandbox; run only trusted targets.

For supported programmatic imports, see the [Python API v1 reference](python-api.md). For CLI and schema compatibility expectations, see the [release policy](release-process.md).
