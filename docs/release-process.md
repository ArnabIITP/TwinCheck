# Release and compatibility policy

## Current status

TwinCheck is public alpha software at version `0.12.0a1`. The first PyPI release has not yet been published. The release-candidate workflow has built and verified wheel and source distributions from the current mainline commit. The GitHub Actions workflows are configured for PyPI Trusted Publishing; the maintainer reports that the PyPI pending publisher and GitHub `pypi` environment have been created, but their account-side settings still need confirmation before publication. Do not tell users to install TwinCheck from PyPI until the first package is actually available.

## Supported compatibility surfaces

| Surface | Current policy |
| --- | --- |
| CLI commands and flags | Documented user interface, but pre-1.0 and allowed to change between alpha releases. Breaking changes must be called out in the changelog and help text. |
| JSON schemas in `docs/*-vN.schema.json` | Versioned artifact formats. Additive optional fields are allowed only when old artifacts remain valid. Breaking format or interpretation changes require a new schema major version/file and migration notes. |
| Stateful sequence and regression-pack files | Their schema filenames define the file-format major version. Unsupported major versions must be rejected rather than silently reinterpreted. |
| Python import API | API v1 is supported through names in `twincheck.api.__all__` and matching package-root exports. Breaking public names, signatures or documented return behavior require an API version increment and migration notes. Internal modules are not covered. |
| Report semantics | Reports are evidence artifacts, not proofs of equivalence or complete records of hidden service state. Version the report schema before changing its meaning incompatibly. |

Because the package is below 1.0, users should pin a package version for reproducible automation and review the changelog before upgrading. The documented Python API v1 has its own compatibility marker; report schemas are versioned independently.

## Validate a release candidate locally

Run from the repository root:

```bash
python -m pip install --upgrade build twine
python -m build --outdir dist
python scripts/verify_distribution.py --dist-dir dist
```

The verifier checks that exactly one wheel and one source archive exist, runs `twine check --strict`, verifies required source-distribution contents, installs the wheel into a temporary virtual environment outside the checkout, and exercises the installed CLI and public API. The build has no runtime dependency installation requirement.

## GitHub Actions workflows

- **CI** runs the test suite, synthetic regression protocols, and distribution verification on Linux/Python 3.11–3.13 and Windows/Python 3.11.
- **Release candidate validation** is manually triggered. It builds and verifies a wheel and source archive, then uploads them as a 14-day artifact. It does not publish to PyPI or create a GitHub release.
- **Prepare GitHub release** runs when a `v*` tag is pushed. It checks that the tag matches the package version, builds and verifies the wheel and source archive, and creates a draft GitHub Release with generated notes and both artifacts attached. A maintainer reviews and publishes the draft manually.
- **PyPI publishing** is triggered only when a GitHub Release is published. It rebuilds and verifies the package from the release tag, checks that the tag matches the version in `pyproject.toml`, and uses PyPI Trusted Publishing through GitHub Actions OIDC. It does not use a long-lived PyPI API token.

## One-time PyPI and GitHub configuration

Before the first public package release:

1. Immediately before publishing, confirm that the normalized PyPI project name `twincheck` is still available. A pending publisher does not reserve the project name; the first successful upload creates the project.
2. Confirm the PyPI pending publisher values are owner `ArnabIITP`, repository `TwinCheck`, workflow filename `publish.yml`, and GitHub environment `pypi`. The workflow path in this repository is `.github/workflows/publish.yml`; PyPI's workflow field expects the filename.
3. Confirm the GitHub environment is named `pypi`, its deployment branch/tag rule permits the release tag, and any configured reviewer can approve the deployment. No environment secrets or variables are required.
4. Confirm the publishing job has only `contents: read` and `id-token: write` permissions. It must use OIDC, not a long-lived PyPI API token.
5. Confirm the package name, version, owner metadata, MIT license, README rendering, source archive contents and release notes before tagging.
6. Keep the GitHub Release in draft until the exact artifacts and release notes have been reviewed. The repository is already public; do not confuse repository visibility with permission to publish a package.

Trusted Publishing must be configured before the first release workflow is expected to publish successfully. Do not add a PyPI API token to repository secrets as a workaround.

## Release checklist

For each alpha release:

1. Choose the next version and update both `pyproject.toml` and `src/twincheck/__init__.py` to the same value.
2. Update `CHANGELOG.md` with user-visible changes, migration notes and known limitations.
3. Run the full CI matrix and all pinned synthetic regression protocols.
4. Run the manual release-candidate workflow and inspect the wheel and source archive.
5. Install the wheel in a clean environment and follow the public [quick-start guide](quickstart.md).
6. Review the README, license, third-party notices, security boundaries, report schemas and compatibility policy.
7. Confirm no reports, credentials, customer data or private evidence are included in the artifacts.
8. Create an annotated tag named `vVERSION` pointing to the reviewed commit. The tag workflow prepares a draft GitHub Release with verified wheel and source artifacts.
9. Review the generated notes and attached artifacts, then publish the GitHub Release only after the configured `pypi` environment approval and Trusted Publisher setup are ready.
10. Verify the PyPI project page and install the exact version from PyPI in a clean environment. Check the installed CLI version and package metadata.

Do not publish a version merely because a workflow passed. The release owner must review the exact source commit and artifacts.

## Security and evidence

TwinCheck is not a sandbox. It executes target commands with the current user's permissions. Real workflow definitions and reports may contain failing inputs and service observations. Do not publish production traces or request bodies without reviewing and sanitizing them.
