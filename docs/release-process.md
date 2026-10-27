# Release and compatibility policy

## Current status

TwinCheck is an early alpha at version 0.12.0a1. The repository has a release-candidate validation workflow, but no PyPI publication is configured or triggered by CI. Successful package validation is not itself a public release.

## What is supported today

| Surface | Current compatibility promise |
| --- | --- |
| CLI commands and flags | Documented user interface, but pre-1.0 and allowed to change between alpha releases. Breaking changes should be called out in the changelog and help text. |
| JSON schemas in `docs/*-vN.schema.json` | Versioned artifact formats. An additive optional field may be added only when old artifacts remain valid and behavior remains compatible. A breaking format or interpretation change requires a new schema major version/file and migration notes. |
| Stateful sequence and regression-pack files | Their schema filenames define the file-format major version. Validation must reject unsupported major versions rather than silently reinterpret them. |
| Python import API | API v1 is supported through the names in `twincheck.api.__all__` and matching package-root exports. Compatible additions preserve `API_VERSION`; breaking public names, signatures or documented return behavior require an API version increment and migration notes. Internal modules are not covered. See [python-api.md](python-api.md). |
| Report semantics | Reports are evidence artifacts, not promises of formal equivalence or a complete record of hidden service state. Version the schema before changing its meaning incompatibly. |

Because the package is below 1.0, users should pin a package version for reproducible automation and review the changelog before upgrading. The documented Python API v1 has its own explicit compatibility marker; report schemas are versioned independently, and neither promise makes internal modules or every CLI detail stable.

## Build and verify locally

Run the same distribution checks as CI from the repository root:

```bash
python -m pip install --upgrade build twine
python -m build --outdir dist
python scripts/verify_distribution.py --dist-dir dist
```

The verifier checks that exactly one wheel and one source archive exist, runs `twine check --strict`, verifies that the source archive contains the license, release documentation, schemas, corpus fixtures, tests and verification script, then creates a clean temporary virtual environment and installs the wheel without dependencies or network access. It checks the installed CLI version and adaptive exploration help from outside the checkout. This catches incomplete source archives and packages that pass tests only because Python imports from the source tree.

## GitHub Actions workflow

The ordinary CI matrix builds and verifies distributions on Linux/Python 3.11–3.13 and Windows/Python 3.11. The verified wheel and source archive from Linux/Python 3.11 are retained as a 14-day release-candidate artifact. The manual **Release candidate validation** workflow runs the build and verification again on request and uploads its artifact.

Neither workflow publishes to PyPI, creates a public release, or tags a version. This is deliberate: repository maintainer review is still required before public release.

## Release checklist

Before publishing a release:

1. Confirm the version in `pyproject.toml` and `src/twincheck/__init__.py` match, and update `CHANGELOG.md`.
2. Run the full CI matrix and the pinned synthetic regression corpus.
3. Run the release-candidate workflow and inspect the built wheel and source archive.
4. Install the wheel in a clean environment and exercise a documented CLI workflow.
5. Inspect the source archive for required documentation, schemas and license material, and ensure it contains no credentials, private reports or temporary evidence.
6. Review the report-schema and API compatibility notes, security boundaries, project URL, license and alpha status.
7. Only after explicit maintainer approval, publish the intended version using a separately configured, least-privilege publishing process. Do not add a token or make publication implicit in the build workflow.
8. Verify the published artifact by installing it from the package index and checking the version and CLI entry point.

## Security and evidence

TwinCheck is not a sandbox. Package validation uses only the checked-in synthetic fixture, but users must still treat real workflow definitions and reports as potentially sensitive. Do not publish production traces or request bodies without reviewing them for secrets and private data.
