# Public Python API v1

TwinCheck exposes a small supported Python API for programmatic command-line differential testing. The API is versioned separately from the package version.

## Supported imports

Import from either the explicit module or package root. Both expose the same objects.

```python
from twincheck.api import API_VERSION, compare_commands, contract_from_dict
```

The package root is also supported:

```python
from twincheck import API_VERSION, compare_commands, contract_from_dict
```

Only names listed in `twincheck.api.__all__` are part of this public surface:

- `API_VERSION`
- `CONTRACT_SCHEMA_VERSION`
- `CompatibilityContract` and `OutputContract`
- `compare_commands`
- `contract_from_dict` and `load_contract`
- `report_as_json`, `write_json_report`, and `write_junit_report`

Other package modules and their internal names may change without API compatibility guarantees.

## Compare two commands

`compare_commands(reference, candidate, ...)` executes both commands for the same generated text inputs and returns a JSON-serializable evidence report.

```python
import shlex
import sys
from twincheck import compare_commands, contract_from_dict, write_json_report

contract = contract_from_dict({
    "name": "parser-compatibility",
    "stdout": {"mode": "exact"},
    "stderr": {"mode": "exact"},
    "compare_exit_code": True,
    "compare_timeout": True,
})

reference_command = shlex.join([sys.executable, "reference.py"])
candidate_command = shlex.join([sys.executable, "replacement.py"])

report = compare_commands(
    reference_command,
    candidate_command,
    cases=100,
    seed=42,
    strategy="mixed",
    timeout=3.0,
    repeat=2,
    contract=contract,
)
write_json_report("reports/compatibility.json", report)

if report["summary"]["differences_found"]:
    print("Observed behavioral differences")
```

Commands are tokenized using TwinCheck's command-string grammar and executed without a shell. This is not a sandbox: targets execute with the current user's permissions. Use trusted commands and synthetic test data. A clean report means only that no difference was observed in the executed cases under the selected comparison policy.

### Comparison options

The supported keyword arguments are:

| Argument | Default | Purpose |
| --- | --- | --- |
| `cases` | `100` | Maximum number of unique inputs to execute |
| `seed` | `0` | Seed for deterministic generation |
| `strategy` | `"mixed"` | One of `mixed`, `text`, `integer`, or `json` |
| `timeout` | `5.0` | Per-process timeout in seconds |
| `cwd` | `None` | Optional working directory for both targets |
| `corpus` | `None` | Directory of known UTF-8 text cases to try before generated cases |
| `minimize` | `False` | Try to shrink stable counterexamples |
| `max_findings_to_minimize` | `1` | Maximum findings to minimize |
| `max_minimization_trials` | `30` | Maximum deletion trials per minimized finding |
| `normalize_eol` | `False` | Treat CRLF, CR and LF as equivalent |
| `ignore_trailing_whitespace` | `False` | Ignore spaces and tabs at line ends |
| `ignore_stderr` | `False` | Exclude stderr from behavioral comparison |
| `ignore_exit_code` | `False` | Exclude exit-code differences |
| `repeat` | `1` | Repeat each case to help expose instability |
| `max_output_bytes` | `1000000` | Retained bytes per output stream |
| `contract` | `None` | Optional validated `CompatibilityContract` |

Invalid options raise `ValueError`. The returned report carries a `schema_version`, execution evidence, finding details, a normalized contract and its SHA-256 fingerprint. Report-field compatibility is governed by the versioned report schema, not just the Python API version.

## Contracts and report output

Use `contract_from_dict(mapping)` for an already-decoded contract or `load_contract(path)` to read a local JSON contract. Both validate the current contract schema. `CompatibilityContract.to_dict()` returns its normalized form and `CompatibilityContract.sha256` fingerprints that normalized representation.

Use `report_as_json(report)` to serialize a report, `write_json_report(path, report)` to write evidence JSON, and `write_junit_report(path, report)` to write JUnit XML. These are output helpers; the report itself remains a normal Python dictionary.

The first public API covers core command-line comparisons and report/contract helpers. Stateful HTTP comparison and exploration are available through the CLI but are not yet exposed as Python API v1 functions.

## Compatibility policy

`API_VERSION = 1` identifies this documented public import surface. Compatible releases may add public names and optional features without changing the API version. A breaking change to exported names, function signatures, or documented return behavior must increment `API_VERSION` and be explained in the changelog with migration guidance. Keep imports from `twincheck.api` or the supported package-root exports; imports from internal implementation modules are not covered.

TwinCheck remains pre-1.0 software. This is a deliberate, tested compatibility commitment for the explicitly exported API, not a claim that every CLI flag, internal module or report field is immutable. Pin the package version when reproducibility matters.
