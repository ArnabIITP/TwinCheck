"""Differential comparison and input minimization."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from .contract import CompatibilityContract, OutputContract, json_output_signature
from .runner import Observation, run_program


@dataclass(frozen=True)
class CompareOptions:
    timeout: float = 5.0
    cwd: str | None = None
    normalize_eol: bool = False
    ignore_trailing_whitespace: bool = False
    ignore_stderr: bool = False
    ignore_exit_code: bool = False
    max_output_bytes: int = 1_000_000
    contract: CompatibilityContract = CompatibilityContract()


def normalize_output(value: str, options: CompareOptions) -> str:
    if options.normalize_eol:
        value = value.replace("\r\n", "\n").replace("\r", "\n")
    if options.ignore_trailing_whitespace:
        value = "\n".join(line.rstrip(" \t") for line in value.split("\n"))
    return value


def _output_signature(value: str, rule: OutputContract, options: CompareOptions) -> tuple[str, object]:
    if rule.mode == "json":
        return json_output_signature(value, rule)
    return "text", normalize_output(value, options)


def difference_kinds(
    reference: Observation,
    candidate: Observation,
    options: CompareOptions,
) -> list[str]:
    differences: list[str] = []
    if options.contract.compare_timeout and reference.timed_out != candidate.timed_out:
        differences.append("timeout")
    if (not options.ignore_exit_code and options.contract.compare_exit_code
            and reference.returncode != candidate.returncode):
        differences.append("exit_code")

    ref_stdout = _output_signature(reference.stdout, options.contract.stdout, options)
    cand_stdout = _output_signature(candidate.stdout, options.contract.stdout, options)
    if "invalid_json" in (ref_stdout[0], cand_stdout[0]):
        differences.append("stdout_invalid_json")
    elif ref_stdout != cand_stdout:
        differences.append("stdout")

    if not options.ignore_stderr:
        ref_stderr = _output_signature(reference.stderr, options.contract.stderr, options)
        cand_stderr = _output_signature(candidate.stderr, options.contract.stderr, options)
        if "invalid_json" in (ref_stderr[0], cand_stderr[0]):
            differences.append("stderr_invalid_json")
        elif ref_stderr != cand_stderr:
            differences.append("stderr")

    if any((reference.stdout_truncated, candidate.stdout_truncated,
            reference.stderr_truncated, candidate.stderr_truncated)):
        differences.append("output_truncated")
    if reference.output_limit_exceeded or candidate.output_limit_exceeded:
        differences.append("output_limit_exceeded")
    return differences


def _behavior_signature(observation: Observation, options: CompareOptions) -> tuple[object, ...]:
    return (
        observation.timed_out if options.contract.compare_timeout else None,
        observation.returncode if (not options.ignore_exit_code and options.contract.compare_exit_code) else None,
        _output_signature(observation.stdout, options.contract.stdout, options),
        _output_signature(observation.stderr, options.contract.stderr, options) if not options.ignore_stderr else None,
        observation.stdout_truncated,
        observation.stderr_truncated,
    )


def execute_pair_runs(
    reference_command: Sequence[str],
    candidate_command: Sequence[str],
    input_text: str,
    options: CompareOptions,
    *,
    repeat: int = 1,
) -> tuple[list[Observation], list[Observation], list[str]]:
    """Execute each implementation repeatedly and report instability explicitly."""
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    reference_runs: list[Observation] = []
    candidate_runs: list[Observation] = []
    for _ in range(repeat):
        reference_runs.append(run_program(
            reference_command, input_text, timeout=options.timeout,
            cwd=options.cwd, max_output_bytes=options.max_output_bytes,
        ))
        candidate_runs.append(run_program(
            candidate_command, input_text, timeout=options.timeout,
            cwd=options.cwd, max_output_bytes=options.max_output_bytes,
        ))

    differences = difference_kinds(reference_runs[0], candidate_runs[0], options)
    if len({_behavior_signature(item, options) for item in reference_runs}) > 1:
        differences.append("reference_unstable")
    if len({_behavior_signature(item, options) for item in candidate_runs}) > 1:
        differences.append("candidate_unstable")
    return reference_runs, candidate_runs, differences


def execute_pair(
    reference_command: Sequence[str],
    candidate_command: Sequence[str],
    input_text: str,
    options: CompareOptions,
    *,
    repeat: int = 1,
) -> tuple[Observation, Observation, list[str]]:
    """Compatibility wrapper returning the first observations plus all findings."""
    reference_runs, candidate_runs, differences = execute_pair_runs(
        reference_command, candidate_command, input_text, options, repeat=repeat
    )
    return reference_runs[0], candidate_runs[0], differences


def minimize_input(
    original: str,
    predicate: Callable[[str], bool],
    *,
    max_trials: int = 500,
) -> tuple[str, int, bool]:
    """Use a delta-debugging strategy to shrink text while preserving a finding.

    Returns ``(minimized_text, trials, trial_limit_reached)``. A minimized input
    is 1-minimal relative to tested deletions, not mathematically globally minimal.
    """
    if max_trials < 1:
        raise ValueError("max_trials must be at least 1")
    current = original
    trials = 0
    granularity = 2

    # Chunk deletion cannot naturally produce the empty string because each
    # candidate removes only a proper slice. Test it explicitly so inputs whose
    # trigger is absence (or an empty/default value) can be minimized correctly.
    if current:
        trials += 1
        try:
            if predicate(""):
                return "", trials, False
        except Exception:
            pass
    else:
        return current, trials, False

    while current and trials < max_trials:
        chunk_size = math.ceil(len(current) / granularity)
        reduced = False
        for start in range(0, len(current), chunk_size):
            candidate = current[:start] + current[start + chunk_size :]
            trials += 1
            try:
                preserves = predicate(candidate)
            except Exception:
                preserves = False
            if preserves:
                current = candidate
                granularity = max(2, granularity - 1)
                reduced = True
                break
            if trials >= max_trials:
                break
        if not reduced:
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    return current, trials, trials >= max_trials
