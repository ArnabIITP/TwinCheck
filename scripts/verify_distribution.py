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
import tempfile
import tomllib
import venv
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

        print(f"Verified wheel: {wheels[0].name}")
        print(f"Verified source archive: {sdists[0].name}")
        print(f"Installed version: {expected_version}")
        print(f"Imported module: {imported_path}")
        print("CLI version/help smoke tests passed outside the source checkout.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        print(f"[FAIL] distribution verification: {exc}", file=sys.stderr)
        raise SystemExit(1)
