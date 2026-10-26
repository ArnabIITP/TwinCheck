"""Orchestrates deterministic differential-testing runs."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from .compare import CompareOptions, execute_pair, minimize_input
from .generators import STRATEGIES, generate_inputs, load_corpus
from .runner import parse_command
from .report import REPORT_SCHEMA_VERSION
from . import __version__


def _finding(
    index: int,
    input_text: str,
    reference: Any,
    candidate: Any,
    differences: list[str],
    *,
    minimized: bool = False,
    minimization_trials: int = 0,
    minimization_limit_reached: bool = False,
) -> dict[str, Any]:
    digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    return {
        "case_index": index,
        "input": input_text,
        "input_sha256": digest,
        "differences": differences,
        "minimized": minimized,
        "minimization_trials": minimization_trials,
        "minimization_limit_reached": minimization_limit_reached,
        "reference": reference.to_dict(),
        "candidate": candidate.to_dict(),
    }


def run_comparison(
    reference: str,
    candidate: str,
    *,
    cases: int = 100,
    seed: int = 0,
    strategy: str = "mixed",
    timeout: float = 2.0,
    cwd: str | None = None,
    corpus: str | None = None,
    minimize: bool = False,
    max_minimize: int = 1,
    max_minimization_trials: int = 30,
    normalize_eol: bool = False,
    ignore_trailing_whitespace: bool = False,
    ignore_stderr: bool = False,
    ignore_exit_code: bool = False,
) -> dict[str, Any]:
    if cases < 1:
        raise ValueError("cases must be at least 1")
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_minimize < 0:
        raise ValueError("max_minimize cannot be negative")
    if minimize and max_minimization_trials < 1:
        raise ValueError("max_minimization_trials must be at least 1 when minimization is enabled")

    reference_argv = parse_command(reference)
    candidate_argv = parse_command(candidate)
    options = CompareOptions(
        timeout=timeout,
        cwd=cwd,
        normalize_eol=normalize_eol,
        ignore_trailing_whitespace=ignore_trailing_whitespace,
        ignore_stderr=ignore_stderr,
        ignore_exit_code=ignore_exit_code,
    )

    input_cases = load_corpus(corpus) if corpus else []
    input_cases = list(dict.fromkeys(input_cases))[:cases]
    if len(input_cases) < cases:
        generated = generate_inputs(max(cases * 2, cases + 30), seed=seed, strategy=strategy)
        seen = set(input_cases)
        for value in generated:
            if value not in seen:
                input_cases.append(value)
                seen.add(value)
            if len(input_cases) >= cases:
                break

    started = time.perf_counter()
    findings: list[dict[str, Any]] = []
    minimizations_done = 0
    for case_index, input_text in enumerate(input_cases, start=1):
        ref_result, candidate_result, differences = execute_pair(
            reference_argv, candidate_argv, input_text, options
        )
        if not differences:
            continue

        item = _finding(case_index, input_text, ref_result, candidate_result, differences)
        if minimize and minimizations_done < max_minimize:
            target_differences = set(differences)

            def preserves(value: str) -> bool:
                _, _, kinds = execute_pair(reference_argv, candidate_argv, value, options)
                return set(kinds) == target_differences

            minimized_input, trials, limit_reached = minimize_input(
                input_text, preserves, max_trials=max_minimization_trials
            )
            minimizations_done += 1
            if minimized_input != input_text:
                ref_result, candidate_result, differences = execute_pair(
                    reference_argv, candidate_argv, minimized_input, options
                )
                item = _finding(
                    case_index,
                    minimized_input,
                    ref_result,
                    candidate_result,
                    differences,
                    minimized=True,
                    minimization_trials=trials,
                    minimization_limit_reached=limit_reached,
                )
            else:
                item["minimization_trials"] = trials
                item["minimization_limit_reached"] = limit_reached
        findings.append(item)

    elapsed = time.perf_counter() - started
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": "TwinCheck",
        "tool_version": __version__,
        "reference_command": reference,
        "candidate_command": candidate,
        "strategy": strategy,
        "seed": seed,
        "cases_requested": cases,
        "cases_executed": len(input_cases),
        "timeout_seconds": timeout,
        "minimization_enabled": minimize,
        "elapsed_seconds": round(elapsed, 6),
        "findings": findings,
        "summary": {
            "differences_found": len(findings),
            "cases_with_differences": len(findings),
            "minimized_findings": sum(1 for finding in findings if finding["minimized"]),
        },
        "limitations": [
            "A clean run is evidence only for the tested inputs, not proof of program equivalence.",
            "Programs are run locally with the current user's permissions; use only trusted commands.",
            "Inputs are UTF-8 text, passed through stdin or a {input} command-argument placeholder.",
        ],
    }
