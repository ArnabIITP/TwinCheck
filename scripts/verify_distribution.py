#!/usr/bin/env python3
"""Validate built TwinCheck distributions from an isolated environment.

This checks the actual wheel, not imports from the checkout. It is intentionally
network-free after the build step: the project has no runtime dependencies.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}"
        )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", required=True, help="directory containing one wheel and one source archive")
    args = parser.parse_args()

    dist_dir = Path(args.dist_dir).resolve()
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted([*dist_dir.glob("*.tar.gz"), *dist_dir.glob("*.zip")])
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(
            f"expected exactly one wheel and one source archive in {dist_dir}; "
            f"found {len(wheels)} wheels and {len(sdists)} source archives"
        )

    with (ROOT / "pyproject.toml").open("rb") as source:
        expected_version = tomllib.load(source)["project"]["version"]

    # Ask Twine to check both uploadable artifacts before installing the wheel.
    print(_run(
        [sys.executable, "-m", "twine", "check", "--strict", str(wheels[0]), str(sdists[0])],
        cwd=ROOT,
    ))

    required_source_files = {
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "LICENSE",
        "docs/release-process.md",
        "docs/python-api.md",
        "docs/report-schema-v1.schema.json",
        "docs/stateful-http-sequence-v1.schema.json",
        "docs/stateful-regression-pack-v1.schema.json",
        "benchmarks/README.md",
        "benchmarks/stateful-corpus-v2/manifest.json",
        "benchmarks/exploration-corpus-v1.schema.json",
        "benchmarks/exploration-corpus-v1/manifest.json",
        "benchmarks/exploration-corpus-v1/service.py",
        "benchmarks/exploration-corpus-v1/sequences/cart-create-add-read-v1.json",
        "benchmarks/exploration-corpus-v1/sequences/cart-create-add-read-twice-v1.json",
        "benchmarks/exploration-corpus-v1/sequences/reset-v1.json",
        "benchmarks/exploration-corpus-v1/contracts/cart-compatibility-v1.json",
        "benchmarks/run_exploration_protocol.py",
        "benchmarks/score_exploration_protocol.py",
        "benchmarks/domain-corpus-v1/manifest.json",
        "benchmarks/domain-corpus-v1/service.py",
        "benchmarks/domain-corpus-v1/run_domain_protocol.py",
        "benchmarks/domain-corpus-v1/sequences/reserve-inspect-v1.json",
        "benchmarks/domain-corpus-v1/sequences/reset-v1.json",
        "benchmarks/domain-corpus-v1/sequences/over-capacity-v1.json",
        "benchmarks/domain-corpus-v1/contracts/inventory-compatibility-v1.json",
        "tests/test_benchmark_scorecard.py",
        "examples/README.md",
        "tests/test_stateful_http.py",
        "tests/test_public_api.py",
        "scripts/verify_distribution.py",
    }
    if sdists[0].name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(sdists[0], "r:gz") as archive:
            source_members = {member.name for member in archive.getmembers() if member.isfile()}
    elif sdists[0].suffix == ".zip":
        with zipfile.ZipFile(sdists[0]) as archive:
            source_members = {name for name in archive.namelist() if not name.endswith("/")}
    else:
        raise RuntimeError(f"unsupported source archive format: {sdists[0].name}")
    missing_source_files = sorted(
        required for required in required_source_files
        if not any(name == required or name.endswith("/" + required) for name in source_members)
    )
    if missing_source_files:
        raise RuntimeError(
            "source archive is missing required project files: " + ", ".join(missing_source_files)
        )
    print(f"Source archive contains all {len(required_source_files)} required docs, schemas, tests and fixtures.")

    with tempfile.TemporaryDirectory(prefix="twincheck-wheel-check-") as temporary:
        temp_path = Path(temporary)
        env_dir = temp_path / "venv"
        working_dir = temp_path / "outside-checkout"
        working_dir.mkdir()
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)

        if os.name == "nt":
            python = env_dir / "Scripts" / "python.exe"
            cli = env_dir / "Scripts" / "twincheck.exe"
        else:
            python = env_dir / "bin" / "python"
            cli = env_dir / "bin" / "twincheck"

        _run(
            [str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheels[0])],
            cwd=working_dir,
        )
        actual_version = _run([str(cli), "--version"], cwd=working_dir)
        expected_cli_version = f"TwinCheck {expected_version}"
        if actual_version != expected_cli_version:
            raise RuntimeError(
                f"installed CLI version mismatch: expected {expected_cli_version!r}, got {actual_version!r}"
            )

        probe = (
            "import importlib.metadata, pathlib, twincheck; "
            "print(importlib.metadata.version('twincheck')); "
            "print(pathlib.Path(twincheck.__file__).resolve())"
        )
        output = _run([str(python), "-c", probe], cwd=working_dir)
        lines = output.splitlines()
        if len(lines) != 2 or lines[0] != expected_version:
            raise RuntimeError(f"unexpected installed-package probe output: {output!r}")
        imported_path = Path(lines[1]).resolve()
        if imported_path.is_relative_to(ROOT):
            raise RuntimeError(
                f"wheel smoke test imported from the source checkout rather than the virtual environment: {imported_path}"
            )

        help_text = _run([str(cli), "explore-http-sequence", "--help"], cwd=working_dir)
        for required_option in ("--mode", "--max-adaptive-candidates", "--max-run-seconds"):
            if required_option not in help_text:
                raise RuntimeError(
                    f"installed CLI help does not expose the expected option {required_option}"
                )

        api_probe = """
import shlex
import sys
from twincheck import API_VERSION, compare_commands, contract_from_dict

assert API_VERSION == 1

def command(code):
    return shlex.join([sys.executable, "-c", code])

report = compare_commands(
    command("import sys;sys.stdout.write(sys.stdin.read().upper())"),
    command("import sys;sys.stdout.write(sys.stdin.read().lower())"),
    cases=3,
    strategy="text",
    seed=0,
    contract=contract_from_dict({"name": "distribution-api-smoke"}),
)
assert report["cases_executed"] == 3
assert report["summary"]["differences_found"] > 0
print("public API v1 smoke test passed")
"""
        api_output = _run([str(python), "-c", api_probe], cwd=working_dir)
        if api_output != "public API v1 smoke test passed":
            raise RuntimeError(f"unexpected public API smoke-test output: {api_output!r}")

        print(f"Verified wheel: {wheels[0].name}")
        print(f"Verified source archive: {sdists[0].name}")
        print(f"Installed version: {expected_version}")
        print(f"Imported module: {imported_path}")
        print("CLI version/help and public Python API smoke tests passed outside the source checkout.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        print(f"[FAIL] distribution verification: {exc}", file=sys.stderr)
        raise SystemExit(1)
