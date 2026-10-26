"""Process execution and observation normalization."""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class Observation:
    """What one program did for one input."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["duration_seconds"] = round(self.duration_seconds, 6)
        return result


def parse_command(command: str) -> list[str]:
    """Parse a command line without invoking a shell."""
    try:
        args = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError(f"could not parse command {command!r}: {exc}") from exc
    if not args:
        raise ValueError("command cannot be empty")
    return args


def run_program(
    command: Sequence[str],
    input_text: str,
    *,
    timeout: float,
    cwd: str | None = None,
) -> Observation:
    """Execute one process and capture its observable behavior.

    Commands are argv sequences, not shell snippets. If any argument contains
    ``{input}``, every occurrence is replaced with the supplied input and stdin is
    left empty; otherwise the input is written to stdin.
    """
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    uses_argument = any("{input}" in part for part in command)
    argv = [part.replace("{input}", input_text) for part in command] if uses_argument else list(command)
    stdin_text = None if uses_argument else input_text
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            check=False,
            shell=False,
        )
        return Observation(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            duration_seconds=time.perf_counter() - started,
        )
    except subprocess.TimeoutExpired as exc:
        def decode(value: str | bytes | None) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return value

        return Observation(
            returncode=None,
            stdout=decode(exc.stdout),
            stderr=decode(exc.stderr),
            timed_out=True,
            duration_seconds=time.perf_counter() - started,
        )
