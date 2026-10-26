"""Differential comparison and input minimization."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from .runner import Observation, run_program


@dataclass(frozen=True)
class CompareOptions:
    timeout: float = 2.0
    cwd: str | None = None
    normalize_eol: bool = False
    ignore_trailing_whitespace: bool = False
    ignore_stderr: bool = False
    ignore_exit_code: bool = False


def normalize_output(value: str, options: CompareOptions) -> str:
    if options.normalize_eol:
        value = value.replace("\r\n", "\n").replace("\r", "\n")
    if options.ignore_trailing_whitespace:
        value = "\n".join(line.rstrip(" \t") for line in value.split("\n"))
    return value


def difference_kinds(
    reference: Observation,
    candidate: Observation,
    options: CompareOptions,
) -> list[str]:
    differences: list[str] = []
    if reference.timed_out != candidate.timed_out:
        differences.append("timeout")
    if not options.ignore_exit_code and reference.returncode != candidate.returncode:
        differences.append("exit_code")
    if normalize_output(reference.stdout, options) != normalize_output(candidate.stdout, options):
        differences.append("stdout")
    if not options.ignore_stderr and normalize_output(reference.stderr, options) != normalize_output(candidate.stderr, options):
        differences.append("stderr")
    return differences


def execute_pair(
    reference_command: Sequence[str],
    candidate_command: Sequence[str],
    input_text: str,
    options: CompareOptions,
) -> tuple[Observation, Observation, list[str]]:
    reference = run_program(reference_command, input_text, timeout=options.timeout, cwd=options.cwd)
    candidate = run_program(candidate_command, input_text, timeout=options.timeout, cwd=options.cwd)
    return reference, candidate, difference_kinds(reference, candidate, options)


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
