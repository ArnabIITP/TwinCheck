"""Supported, versioned Python API for TwinCheck.

Only names listed in __all__ are part of the supported import surface.
Implementation modules remain private to the package compatibility contract.
"""
from __future__ import annotations

from typing import Any

from .contract import (
    CONTRACT_SCHEMA_VERSION,
    CompatibilityContract,
    OutputContract,
    contract_from_dict,
    load_contract,
)
from .engine import run_comparison
from .report import report_as_json, write_json_report, write_junit_report

# Increment this only when an intentional breaking change is made to the public
# Python symbols, signatures, or documented return contract.
API_VERSION = 1


def compare_commands(
    reference: str,
    candidate: str,
    *,
    cases: int = 100,
    seed: int = 0,
    strategy: str = "mixed",
    timeout: float = 5.0,
    cwd: str | None = None,
    corpus: str | None = None,
    minimize: bool = False,
    max_findings_to_minimize: int = 1,
    max_minimization_trials: int = 30,
    normalize_eol: bool = False,
    ignore_trailing_whitespace: bool = False,
    ignore_stderr: bool = False,
    ignore_exit_code: bool = False,
    repeat: int = 1,
    max_output_bytes: int = 1_000_000,
    contract: CompatibilityContract | None = None,
) -> dict[str, Any]:
    """Compare two local commands and return a JSON-serializable evidence report.

    Commands are parsed into argument vectors and executed without a shell.
    They still run with the current user's permissions: only run trusted
    commands. The report describes observations from the cases actually run;
    a clean result is not proof of equivalence for all inputs.
    """
    return run_comparison(
        reference,
        candidate,
        cases=cases,
        seed=seed,
        strategy=strategy,
        timeout=timeout,
        cwd=cwd,
        corpus=corpus,
        minimize=minimize,
        max_minimize=max_findings_to_minimize,
        max_minimization_trials=max_minimization_trials,
        normalize_eol=normalize_eol,
        ignore_trailing_whitespace=ignore_trailing_whitespace,
        ignore_stderr=ignore_stderr,
        ignore_exit_code=ignore_exit_code,
        repeat=repeat,
        max_output_bytes=max_output_bytes,
        contract=contract,
    )


__all__ = [
    "API_VERSION",
    "CONTRACT_SCHEMA_VERSION",
    "CompatibilityContract",
    "OutputContract",
    "compare_commands",
    "contract_from_dict",
    "load_contract",
    "report_as_json",
    "write_json_report",
    "write_junit_report",
]
