# Contributing to TwinCheck

Thanks for helping improve TwinCheck. The project prioritizes reproducible findings, small understandable changes and honest statements about limitations.

## Before opening an issue

- Search existing issues for duplicates.
- Include TwinCheck version, Python version, operating system, a minimal command, the seed and a sanitized report when possible.
- Remove credentials, personal data, proprietary inputs and confidential logs before sharing traces.

## Development setup

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m pip install --upgrade build twine
python -m build --outdir dist
python scripts/verify_distribution.py --dist-dir dist
```

The distribution check validates the built wheel and source archive, then installs the wheel into a temporary environment outside the checkout and exercises the CLI entry point. No runtime dependencies are required. Keep the test suite runnable with the Python standard library wherever practical.

## Pull request expectations

1. Describe the behavior changed and why it matters.
2. Add a regression test for bug fixes.
3. Keep the same seed reproducible and avoid using process-global random state.
4. Preserve the principle that reports contain executed evidence, not guessed explanations.
5. Update docs and the roadmap when behavior or scope changes.
6. Do not introduce network activity or API keys into the core engine.

## Code style

Follow standard Python conventions, add types for public interfaces, keep functions focused, and prefer clear error messages over silent fallback. Do not broaden permissions or use `shell=True` to make a command work.

## Release and compatibility policy

Before changing CLI flags, report schemas or file formats, read [the release and compatibility policy](docs/release-process.md). TwinCheck is pre-1.0: the Python import API is not stable, and changes to documented interfaces must be reflected in the changelog and relevant schema/version notes. The manual release-candidate workflow builds and verifies artifacts; it intentionally does not publish packages.

## Security-sensitive changes

Please read [SECURITY.md](SECURITY.md). Do not run unknown submissions locally. TwinCheck currently executes target commands using the user's privileges and is not a sandbox.
