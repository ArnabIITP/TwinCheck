"""Shell-free process execution with bounded temporary-file output capture."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class Observation:
    """Observable behavior of one process for one input."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_bytes_seen: int = 0
    stderr_bytes_seen: int = 0
    output_limit_exceeded: bool = False

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["duration_seconds"] = round(self.duration_seconds, 6)
        return result


def parse_command(command: str) -> list[str]:
    """Parse command text with POSIX-like quoting, without invoking a shell.

    Using one quoting grammar keeps command strings portable between the
    documented examples on Linux, macOS and Windows. For complex platform paths
    or arguments with unusual quoting, prefer simple wrapper scripts.
    """
    try:
        args = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError(f"could not parse command {command!r}: {exc}") from exc
    if not args:
        raise ValueError("command cannot be empty")
    return args


def _kill_process_group(process: subprocess.Popen[bytes], *, force: bool) -> None:
    """Best-effort cleanup for the target and descendants on POSIX."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif process.poll() is None:
            process.kill() if force else process.terminate()
    except (ProcessLookupError, OSError):
        pass


def _read_capped(handle, limit: int) -> tuple[str, int, bool]:
    handle.flush()
    size = os.fstat(handle.fileno()).st_size
    handle.seek(0)
    data = handle.read(limit)
    return data.decode("utf-8", errors="replace"), size, size > limit


def run_program(
    command: Sequence[str],
    input_text: str,
    *,
    timeout: float,
    cwd: str | None = None,
    max_output_bytes: int = 1_000_000,
) -> Observation:
    """Run one command and retain no more than max_output_bytes per output stream.

    Text is passed on stdin unless an argv element contains ``{input}``, in which
    case the token is replaced and stdin is empty. Output is redirected to
    temporary files instead of pipes, avoiding pipe deadlocks and unbounded
    in-memory capture. The runner polls output file sizes and kills the target
    if the retention limit is exceeded. POSIX targets run in a fresh process
    group so timeout cleanup also attempts to stop descendants.

    This is resource-conscious test execution, not a security sandbox. Targets
    still run with the caller's privileges; OS-specific containment is required
    before accepting untrusted commands.
    """
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be at least 1")
    if not command:
        raise ValueError("command cannot be empty")

    uses_argument = any("{input}" in part for part in command)
    argv = [part.replace("{input}", input_text) for part in command] if uses_argument else list(command)
    payload = b"" if uses_argument else input_text.encode("utf-8")
    started = time.perf_counter()
    timed_out = False
    output_limit_exceeded = False

    # TemporaryFile creates OS-backed files that are removed automatically at
    # close. Input is also file-backed, avoiding a writer-thread deadlock if a
    # target never consumes stdin.
    with tempfile.TemporaryFile(mode="w+b") as input_file, \
         tempfile.TemporaryFile(mode="w+b") as stdout_file, \
         tempfile.TemporaryFile(mode="w+b") as stderr_file:
        input_file.write(payload)
        input_file.seek(0)
        try:
            process = subprocess.Popen(
                argv,
                stdin=input_file,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=cwd,
                shell=False,
                start_new_session=(os.name == "posix"),
            )
        except (OSError, ValueError) as exc:
            raise ValueError(f"could not start command {argv!r}: {exc}") from exc

        deadline = time.monotonic() + timeout
        while process.poll() is None:
            stdout_size = os.fstat(stdout_file.fileno()).st_size
            stderr_size = os.fstat(stderr_file.fileno()).st_size
            if stdout_size > max_output_bytes or stderr_size > max_output_bytes:
                output_limit_exceeded = True
                # Force-kill now: waiting for a graceful exit could allow a
                # runaway writer to consume more temporary storage.
                _kill_process_group(process, force=True)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _kill_process_group(process, force=False)
                try:
                    process.wait(timeout=0.15)
                except subprocess.TimeoutExpired:
                    pass
                # Kill any remaining group members, including children after
                # the direct process exits due to SIGTERM.
                _kill_process_group(process, force=True)
                break
            time.sleep(0.005)

        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_group(process, force=True)
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass

        stdout, stdout_bytes_seen, stdout_truncated = _read_capped(stdout_file, max_output_bytes)
        stderr, stderr_bytes_seen, stderr_truncated = _read_capped(stderr_file, max_output_bytes)
        # A very short-lived process may finish before the next polling tick.
        # It is still important to report that the retained artifact is partial.
        output_limit_exceeded = output_limit_exceeded or stdout_truncated or stderr_truncated

    return Observation(
        returncode=None if timed_out else process.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_seconds=time.perf_counter() - started,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stdout_bytes_seen=stdout_bytes_seen,
        stderr_bytes_seen=stderr_bytes_seen,
        output_limit_exceeded=output_limit_exceeded,
    )
