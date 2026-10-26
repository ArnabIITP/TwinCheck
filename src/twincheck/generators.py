"""Deterministic, dependency-free input generation for differential testing."""

from __future__ import annotations

import json
import random
import string
from pathlib import Path
from typing import Any

STRATEGIES = ("mixed", "text", "integer", "json")

_TEXT_EDGE_CASES = [
    "", "a", "A", "0", "-1", " ", "  ", "\n", "\t", "hello", "hello\n",
    "a\nb\n", " leading", "trailing ", "\r\n", "é", "你好", "🙂",
    "quote'slash\\", "null", "NaN", "0.0", "TRUE", "false", "a" * 128,
    "line\rbreak", "x\x00y",
]
_INTEGER_EDGE_CASES = [
    "-9223372036854775808", "-2147483649", "-2147483648", "-32769", "-32768",
    "-2", "-1", "0", "1", "2", "32767", "32768", "2147483647",
    "2147483648", "9223372036854775807", "9223372036854775808",
    "-9999999999999999999999999", "9999999999999999999999999",
]
_JSON_EDGE_CASES = [
    "null", "true", "false", "0", "-1", "1.5", '""', '"hello"', '"é🙂"',
    "[]", "{}", "[1,2,3]", '{"a":1}', '{"a":null,"b":false}',
    '["newline\\n","quote\\\"","backslash\\\\"]',
    '{"nested":{"items":[1,"two",null]},"empty":[]}',
    "[0, -1, 9223372036854775808, 1.0e-12]",
]


def _random_json_value(rng: random.Random, depth: int = 0) -> Any:
    """Return a small JSON-compatible value with bounded nesting."""
    scalar = [
        None, True, False, rng.randint(-(10**9), 10**9), rng.random(),
        "".join(rng.choices(string.ascii_letters + " _-é🙂", k=rng.randint(0, 18))),
    ]
    if depth >= 3:
        return rng.choice(scalar)
    kind = rng.randrange(5)
    if kind == 0:
        return rng.choice(scalar)
    if kind in (1, 2):
        return [_random_json_value(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    return {
        "".join(rng.choices(string.ascii_lowercase + "_", k=rng.randint(1, 8))):
        _random_json_value(rng, depth + 1)
        for _ in range(rng.randint(0, 5))
    }


def _random_text(rng: random.Random) -> str:
    alphabet = string.ascii_letters + string.digits + " \t\n\r_-.!?:/\\\\'\"[]{}()é🙂\x00"
    return "".join(rng.choices(alphabet, k=rng.randint(0, 100)))


def _random_integer(rng: random.Random) -> str:
    mode = rng.randrange(4)
    if mode == 0:
        return str(rng.randint(-100, 100))
    if mode == 1:
        return str(rng.randint(-(2**31), 2**31 - 1))
    if mode == 2:
        return str(rng.randint(-(10**30), 10**30))
    return rng.choice(["+0", "-0", "00", "0001", "-0001"])


def _random_input(rng: random.Random, strategy: str) -> str:
    if strategy == "text":
        return _random_text(rng)
    if strategy == "integer":
        return _random_integer(rng)
    if strategy == "json":
        return json.dumps(_random_json_value(rng), ensure_ascii=False, separators=(",", ":"))
    selected = rng.choice(("text", "integer", "json"))
    return _random_input(rng, selected)


def _edge_cases(strategy: str) -> list[str]:
    if strategy == "text":
        return list(_TEXT_EDGE_CASES)
    if strategy == "integer":
        return list(_INTEGER_EDGE_CASES)
    if strategy == "json":
        return list(_JSON_EDGE_CASES)
    return list(dict.fromkeys(_TEXT_EDGE_CASES + _INTEGER_EDGE_CASES + _JSON_EDGE_CASES))


def generate_inputs(count: int, seed: int = 0, strategy: str = "mixed") -> list[str]:
    """Generate up to count unique UTF-8 text inputs reproducibly for a seed.

    Known edge cases are tried first, followed by seeded pseudo-random values.
    Programs receive each case on stdin unless the command includes the
    explicit {input} argument placeholder.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")

    rng = random.Random(seed)
    results: list[str] = []
    seen: set[str] = set()
    for value in _edge_cases(strategy):
        if value not in seen:
            results.append(value)
            seen.add(value)
        if len(results) >= count:
            return results

    attempts = 0
    max_attempts = max(100, count * 30)
    while len(results) < count and attempts < max_attempts:
        attempts += 1
        value = _random_input(rng, strategy)
        if value not in seen:
            results.append(value)
            seen.add(value)

    # Defensive fallback keeps the requested-count contract for future
    # strategies whose generated domain might be unusually small.
    while len(results) < count:
        value = f"twincheck-generated-{len(results)}-{seed}"
        if value not in seen:
            results.append(value)
            seen.add(value)
    return results


def load_corpus(path: str) -> list[str]:
    """Load a directory of UTF-8 input files in stable path order."""
    root = Path(path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"corpus path must be an existing directory: {root}")
    cases: list[str] = []
    for file_path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            cases.append(file_path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError(f"corpus file is not UTF-8 text: {file_path}") from exc
    return list(dict.fromkeys(cases))
