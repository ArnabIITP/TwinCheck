"""Orchestrates deterministic differential-testing runs."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Sequence

from .compare import CompareOptions, execute_pair_runs, minimize_input
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
    reference_runs: list[Any] | None = None,
    candidate_runs: list[Any] | None = None,
) -> dict[str, Any]:
    digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    finding = {
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
    if reference_runs is not None and len(reference_runs) > 1:
        finding["reference_runs"] = [item.to_dict() for item in reference_runs]
    if candidate_runs is not None and len(candidate_runs) > 1:
        finding["candidate_runs"] = [item.to_dict() for item in candidate_runs]
    return finding


def run_comparison(
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
    max_minimize: int = 1,
    max_minimization_trials: int = 30,
    normalize_eol: bool = False,
    ignore_trailing_whitespace: bool = False,
    ignore_stderr: bool = False,
    ignore_exit_code: bool = False,
    repeat: int = 1,
    max_output_bytes: int = 1_000_000,
    input_cases: Sequence[str] | None = None,
    input_source: str | None = None,
) -> dict[str, Any]:
    if cases < 1:
        raise ValueError("cases must be at least 1")
    if input_cases is None and strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_minimize < 0:
        raise ValueError("max_minimize cannot be negative")
    if minimize and max_minimization_trials < 1:
        raise ValueError("max_minimization_trials must be at least 1 when minimization is enabled")
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be at least 1")

    reference_argv = parse_command(reference)
    candidate_argv = parse_command(candidate)
    options = CompareOptions(
        timeout=timeout,
        cwd=cwd,
        normalize_eol=normalize_eol,
        ignore_trailing_whitespace=ignore_trailing_whitespace,
        ignore_stderr=ignore_stderr,
        ignore_exit_code=ignore_exit_code,
        max_output_bytes=max_output_bytes,
    )

    explicit_inputs = input_cases is not None
    if explicit_inputs:
        selected_inputs = list(dict.fromkeys(input_cases or []))[:cases]
        if not selected_inputs:
            raise ValueError("explicit input_cases must contain at least one input")
    else:
        selected_inputs = load_corpus(corpus) if corpus else []
        selected_inputs = list(dict.fromkeys(selected_inputs))[:cases]
        if len(selected_inputs) < cases:
            generated = generate_inputs(max(cases * 2, cases + 30), seed=seed, strategy=strategy)
            seen = set(selected_inputs)
            for value in generated:
                if value not in seen:
                    selected_inputs.append(value)
                    seen.add(value)
                if len(selected_inputs) >= cases:
                    break

    started = time.perf_counter()
    findings: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    minimizations_done = 0
    for case_index, input_text in enumerate(selected_inputs, start=1):
        ref_runs, candidate_runs, differences = execute_pair_runs(
            reference_argv, candidate_argv, input_text, options, repeat=repeat
        )
        ref_result, candidate_result = ref_runs[0], candidate_runs[0]
        digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
        executions.append({
            "case_index": case_index,
            "input_sha256": digest,
            "differences": list(differences),
        })
        if not differences:
            continue

        item = _finding(
            case_index, input_text, ref_result, candidate_result, differences,
            reference_runs=ref_runs, candidate_runs=candidate_runs,
        )
        unstable = {"reference_unstable", "candidate_unstable"}
        deterministic_differences = set(differences) - unstable
        # Minimization is only meaningful when the original mismatch is stable.
        if (minimize and minimizations_done < max_minimize and deterministic_differences
                and not (set(differences) & unstable)):
            target_differences = deterministic_differences

            def preserves(value: str) -> bool:
                _, _, kinds = execute_pair_runs(
                    reference_argv, candidate_argv, value, options, repeat=repeat
                )
                return set(kinds) == target_differences

            minimized_input, trials, limit_reached = minimize_input(
                input_text, preserves, max_trials=max_minimization_trials
            )
            minimizations_done += 1
            if minimized_input != input_text:
                ref_runs, candidate_runs, differences = execute_pair_runs(
                    reference_argv, candidate_argv, minimized_input, options, repeat=repeat
                )
                ref_result, candidate_result = ref_runs[0], candidate_runs[0]
                item = _finding(
                    case_index,
                    minimized_input,
                    ref_result,
                    candidate_result,
                    differences,
                    minimized=True,
                    minimization_trials=trials,
                    minimization_limit_reached=limit_reached,
                    reference_runs=ref_runs,
                    candidate_runs=candidate_runs,
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
        "repeat": repeat,
        "max_output_bytes": max_output_bytes,
        "working_directory": cwd,
        "comparison_policy": {
            "normalize_eol": normalize_eol,
            "ignore_trailing_whitespace": ignore_trailing_whitespace,
            "ignore_stderr": ignore_stderr,
            "ignore_exit_code": ignore_exit_code,
        },
        "input_source": input_source or ("explicit" if explicit_inputs else ("corpus+generated" if corpus else "generated")),
        "cases_requested": cases,
        "cases_executed": len(selected_inputs),
        "timeout_seconds": timeout,
        "minimization_enabled": minimize,
        "executions": executions,
        "elapsed_seconds": round(elapsed, 6),
        "findings": findings,
        "summary": {
            "differences_found": len(findings),
            "cases_with_differences": len(findings),
            "minimized_findings": sum(1 for finding in findings if finding["minimized"]),
            "unstable_reference_findings": sum(1 for finding in findings if "reference_unstable" in finding["differences"]),
            "unstable_candidate_findings": sum(1 for finding in findings if "candidate_unstable" in finding["differences"]),
            "truncated_output_findings": sum(1 for finding in findings if "output_truncated" in finding["differences"]),
            "output_limit_findings": sum(1 for finding in findings if "output_limit_exceeded" in finding["differences"]),
        },
        "limitations": [
            "A clean run is evidence only for the tested inputs, not proof of program equivalence.",
            "Programs are run locally with the current user's permissions; use only trusted commands.",
            "Inputs are UTF-8 text, passed through stdin or a {input} command-argument placeholder.",
            "Output retention is capped independently per stream; truncated observations are flagged and are not complete transcripts.",
            "Repeated runs detect observable instability but cannot explain or eliminate all nondeterminism.",
        ],
    }
