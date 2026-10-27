"""Deterministic, reset-backed exploration of stateful HTTP workflows."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import __version__
from .contract import CompatibilityContract, OutputContract
from .report import REPORT_SCHEMA_VERSION
from .stateful_http import run_http_sequence_comparison, validate_sequence

_MAX_EXPLORE_CASES = 200
_MAX_MINIMIZATION_TRIALS = 200
_TEMPLATE_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


@dataclass(frozen=True)
class SequenceVariant:
    sequence: dict[str, Any]
    mutation_type: str
    description: str
    sha256: str


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _variables_used(step: Mapping[str, Any]) -> set[str]:
    strings = [step.get("path", "")]
    if "body" in step:
        strings.extend(_strings(step["body"]))
    return {match.group(1) for value in strings for match in _TEMPLATE_RE.finditer(value)}


def _has_valid_capture_order(sequence: Mapping[str, Any]) -> bool:
    captured: set[str] = set()
    for step in sequence.get("steps", []):
        if not _variables_used(step).issubset(captured):
            return False
        captures = step.get("capture", {})
        if not isinstance(captures, dict):
            return False
        captured.update(captures)
    return True


def _valid_variant(sequence: dict[str, Any]) -> bool:
    try:
        validate_sequence(sequence)
    except (ValueError, TypeError, RecursionError):
        return False
    return _has_valid_capture_order(sequence)


def _leaf_values(value: Any, path: tuple[str | int, ...] = ()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaf_values(item, path + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaf_values(item, path + (index,))
    elif value is None or isinstance(value, (str, int, float, bool)):
        yield path, value


def _set_nested(value: Any, path: tuple[str | int, ...], replacement: Any) -> Any:
    if not path:
        return replacement
    head, *tail = path
    if isinstance(value, dict):
        clone = dict(value)
        clone[str(head)] = _set_nested(clone[str(head)], tuple(tail), replacement)
        return clone
    if isinstance(value, list):
        clone = list(value)
        clone[int(head)] = _set_nested(clone[int(head)], tuple(tail), replacement)
        return clone
    raise ValueError("mutation path does not identify a JSON value")


def _path_pointer(path: tuple[str | int, ...]) -> str:
    if not path:
        return "(root)"
    return "/" + "/".join(str(item).replace("~", "~0").replace("/", "~1") for item in path)


def _alternatives(value: Any) -> list[Any]:
    if isinstance(value, bool):
        candidates = [not value, None, 0 if value else 1, "true" if value else "false"]
    elif value is None:
        candidates = [0, "", False, "twincheck-boundary", []]
    elif isinstance(value, int):
        candidates = [0, -1, 1, 2**31 - 1, None, "not-a-number"]
    elif isinstance(value, float):
        candidates = [0.0, -1.0, value + 0.5, None, "not-a-number"]
    elif isinstance(value, str):
        candidates = ["", " ", value + "-mutated", "twincheck-boundary", None, 0]
    else:
        return []
    original = _canonical(value)
    result: list[Any] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = _canonical(candidate)
        if marker != original and marker not in seen:
            seen.add(marker)
            result.append(candidate)
    return result


def _variant_sequence(base: Mapping[str, Any], steps: list[dict[str, Any]], label: str) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(base))
    candidate["steps"] = steps
    candidate_name = f"{base.get('name', 'workflow')} [{label}]"
    candidate["name"] = candidate_name[:120]
    return candidate


def _same_steps_digest(sequence: Mapping[str, Any]) -> str:
    return _sha256_text(_canonical(sequence.get("steps", [])))


def _has_direct_dependency(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_produces = set(left.get("capture", {}))
    right_produces = set(right.get("capture", {}))
    left_name, right_name = left.get("name"), right.get("name")
    return bool(
        left_produces & _variables_used(right)
        or right_produces & _variables_used(left)
        or left_produces & right_produces
        or (isinstance(right_name, str) and right_name in left.get("depends_on", []))
        or (isinstance(left_name, str) and left_name in right.get("depends_on", []))
    )


def generate_sequence_variants(sequence: Mapping[str, Any], *, max_cases: int, seed: int = 0) -> list[SequenceVariant]:
    """Return baseline plus deterministic body, order, removal and repetition variants."""
    validate_sequence(dict(sequence))
    if not _has_valid_capture_order(sequence):
        raise ValueError("sequence references a template variable before it is captured")
    if type(max_cases) is not int or not 1 <= max_cases <= _MAX_EXPLORE_CASES:
        raise ValueError(f"max_cases must be between 1 and {_MAX_EXPLORE_CASES}")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")

    base = copy.deepcopy(dict(sequence))
    base_name = str(base.get("name", "workflow"))
    categories: dict[str, list[tuple[dict[str, Any], str]]] = {
        "value_boundary": [], "order_swap": [], "step_removal": [], "step_repeat": []
    }
    per_category_limit = max(4, max_cases * 4)

    # Change one JSON scalar in one body per variant. Captured templates are not
    # mutated as if they were literal API data.
    for index, step in enumerate(base["steps"]):
        if "body" not in step:
            continue
        for path, value in _leaf_values(step["body"]):
            if isinstance(value, str) and _TEMPLATE_RE.search(value):
                continue
            for alternative in _alternatives(value):
                changed_steps = copy.deepcopy(base["steps"])
                changed_steps[index]["body"] = _set_nested(changed_steps[index]["body"], path, alternative)
                pointer = _path_pointer(path)
                label = f"value:{step.get('name', index + 1)}:{pointer}"
                candidate = _variant_sequence(base, changed_steps, label)
                if _valid_variant(candidate):
                    categories["value_boundary"].append((candidate, f"replace {step.get('name', index + 1)} body{pointer} with {type(alternative).__name__}"))
                if len(categories["value_boundary"]) >= per_category_limit:
                    break
            if len(categories["value_boundary"]) >= per_category_limit:
                break
        if len(categories["value_boundary"]) >= per_category_limit:
            break

    # Adjacent swaps explore local transition order while preserving explicit
    # capture dependencies. The API's state machine, not TwinCheck, decides if
    # the new ordering is semantically valid.
    for index in range(len(base["steps"]) - 1):
        left, right = base["steps"][index:index + 2]
        if _has_direct_dependency(left, right):
            continue
        changed_steps = copy.deepcopy(base["steps"])
        changed_steps[index], changed_steps[index + 1] = changed_steps[index + 1], changed_steps[index]
        candidate = _variant_sequence(base, changed_steps, f"swap:{index + 1}-{index + 2}")
        if _valid_variant(candidate):
            categories["order_swap"].append((candidate, f"swap adjacent steps {index + 1} and {index + 2}"))

    # Removing or repeating a transition reveals hidden prerequisites, duplicate
    # operation behavior, and effects that depend on operation count.
    for index in range(len(base["steps"])):
        remaining = copy.deepcopy(base["steps"][:index] + base["steps"][index + 1:])
        if remaining:
            candidate = _variant_sequence(base, remaining, f"remove:{index + 1}")
            if _valid_variant(candidate):
                categories["step_removal"].append((candidate, f"remove step {index + 1} ({base['steps'][index].get('name', index + 1)})"))

        if len(base["steps"]) >= 25:
            continue
        repeated = copy.deepcopy(base["steps"])
        duplicate = copy.deepcopy(repeated[index])
        original_name = str(duplicate.get("name", f"step-{index + 1}"))
        duplicate["name"] = (original_name[:105] + f"-repeat-{index + 1}")[:120]
        existing_names = {item.get("name") for item in repeated}
        while duplicate["name"] in existing_names:
            duplicate["name"] = (duplicate["name"][:110] + "x")[:120]
        repeated.insert(index + 1, duplicate)
        candidate = _variant_sequence(base, repeated, f"repeat:{index + 1}")
        if _valid_variant(candidate):
            categories["step_repeat"].append((candidate, f"repeat step {index + 1} ({original_name}) once"))

    rng = random.Random(seed)
    for items in categories.values():
        rng.shuffle(items)
    order = list(categories)
    rng.shuffle(order)
    variants: list[SequenceVariant] = []
    seen: set[str] = {_same_steps_digest(base)}
    while len(variants) < max_cases - 1:
        added = False
        for category in order:
            while categories[category]:
                candidate, description = categories[category].pop()
                digest = _same_steps_digest(candidate)
                if digest in seen:
                    continue
                seen.add(digest)
                variants.append(SequenceVariant(candidate, category, description, _sha256_text(_canonical(candidate))))
                added = True
                break
            if len(variants) >= max_cases - 1:
                break
        if not added:
            break

    baseline_digest = _sha256_text(_canonical(base))
    return [SequenceVariant(base, "baseline", "run the original workflow", baseline_digest), *variants]


def _target_failure(finding: Mapping[str, Any]) -> tuple[str, set[str]] | None:
    trace = finding.get("step_results", [])
    if not isinstance(trace, list):
        return None
    for step in trace:
        if isinstance(step, dict) and isinstance(step.get("differences"), list) and step["differences"]:
            return str(step.get("name", "")), set(str(item) for item in step["differences"])
    return None


def _preserves_target_failure(report: Mapping[str, Any], target_name: str, target_categories: set[str]) -> bool:
    for finding in report.get("findings", []):
        for step in finding.get("step_results", []):
            if step.get("name") == target_name and set(step.get("differences", [])) & target_categories:
                return True
    return False


def _minimize_steps(
    sequence: dict[str, Any],
    *,
    target_name: str,
    target_categories: set[str],
    run_candidate,
    trial_budget: int,
) -> tuple[dict[str, Any], int, bool]:
    current = copy.deepcopy(sequence)
    trials = 0
    granularity = 2
    budget_hit = False
    while len(current["steps"]) > 1 and trials < trial_budget:
        step_count = len(current["steps"])
        chunk_size = max(1, (step_count + granularity - 1) // granularity)
        accepted = False
        for start in range(0, step_count, chunk_size):
            if trials >= trial_budget:
                budget_hit = True
                break
            candidate_steps = copy.deepcopy(current["steps"][:start] + current["steps"][start + chunk_size:])
            if not candidate_steps:
                continue
            candidate = _variant_sequence(current, candidate_steps, "minimized")
            if not _valid_variant(candidate):
                continue
            trial_report = run_candidate(candidate)
            trials += 1
            if _preserves_target_failure(trial_report, target_name, target_categories):
                current = candidate
                granularity = max(2, granularity - 1)
                accepted = True
                break
        if budget_hit:
            break
        if not accepted:
            if granularity >= step_count:
                break
            granularity = min(step_count, granularity * 2)
    if trials >= trial_budget and len(current["steps"]) > 1:
        budget_hit = True
    return current, trials, budget_hit


def _value_cost(value: Any) -> int:
    """A small, deterministic complexity measure used by value minimization."""
    if value is None:
        return 1
    if isinstance(value, bool):
        return 1 if value is False else 2
    if isinstance(value, int):
        return 1 if value == 0 else 1 + len(str(abs(value)))
    if isinstance(value, float):
        return 1 if value == 0.0 else 1 + len(str(abs(value)))
    if isinstance(value, str):
        return 1 + len(value)
    if isinstance(value, list):
        return 1 + sum(_value_cost(item) for item in value)
    if isinstance(value, dict):
        return 1 + sum(1 + len(str(key)) + _value_cost(item) for key, item in value.items())
    return len(_canonical(value))


def _shrink_candidates(value: Any) -> list[Any]:
    """Produce smaller JSON values by deleting structure or simplifying scalars."""
    candidates: list[Any] = []
    if isinstance(value, dict):
        for key in sorted(value):
            reduced = dict(value)
            del reduced[key]
            candidates.append(reduced)
            for child in _shrink_candidates(value[key]):
                reduced_child = dict(value)
                reduced_child[key] = child
                candidates.append(reduced_child)
    elif isinstance(value, list):
        for index in range(len(value)):
            candidates.append(value[:index] + value[index + 1:])
            for child in _shrink_candidates(value[index]):
                reduced_child = list(value)
                reduced_child[index] = child
                candidates.append(reduced_child)
    elif isinstance(value, bool):
        if value:
            candidates.append(False)
    elif isinstance(value, int):
        candidates.extend(item for item in (0, 1, -1) if item != value)
    elif isinstance(value, float):
        candidates.extend(item for item in (0.0, 1.0, -1.0) if item != value)
    elif isinstance(value, str):
        candidates.append("")
        if value:
            candidates.append(value[: max(1, len(value) // 2)])
            candidates.append("a")

    original_cost = _value_cost(value)
    unique: dict[str, Any] = {}
    for candidate in candidates:
        try:
            marker = _canonical(candidate)
        except (TypeError, ValueError, RecursionError):
            continue
        if marker != _canonical(value) and _value_cost(candidate) < original_cost:
            unique[marker] = candidate
    return sorted(unique.values(), key=lambda item: (_value_cost(item), len(_canonical(item)), _canonical(item)))


def _walk_value_differences(before: Any, after: Any, pointer: str = ""):
    """Yield changed body paths and candidate value fingerprints (never values)."""
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            segment = str(key).replace("~", "~0").replace("/", "~1")
            child_pointer = pointer + "/" + segment
            if key not in before:
                value = after[key]
                yield child_pointer, "added", _sha256_text(_canonical(value))[:12]
            elif key not in after:
                yield child_pointer, "removed", "missing"
            else:
                yield from _walk_value_differences(before[key], after[key], child_pointer)
        return
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            yield pointer or "/", "array-length", str(len(after))
        for index, (left, right) in enumerate(zip(before, after)):
            yield from _walk_value_differences(left, right, pointer + f"/{index}")
        return
    try:
        equal = _canonical(before) == _canonical(after)
    except (TypeError, ValueError, RecursionError):
        equal = before == after
    if not equal:
        if after is None:
            bucket = "null"
        elif isinstance(after, bool):
            bucket = "boolean"
        elif isinstance(after, int):
            bucket = "integer"
        elif isinstance(after, float):
            bucket = "number"
        elif isinstance(after, str):
            bucket = "string"
        elif isinstance(after, list):
            bucket = "array"
        elif isinstance(after, dict):
            bucket = "object"
        else:
            bucket = type(after).__name__
        yield pointer or "/", bucket, _sha256_text(_canonical(after))[:12]


def _variant_mutation_features(base: Mapping[str, Any], variant: SequenceVariant) -> tuple[set[str], set[str]]:
    """Map a candidate to the workflow steps and bounded mutation features it touches."""
    base_steps = list(base.get("steps", []))
    candidate_steps = list(variant.sequence.get("steps", []))
    base_by_name = {str(step.get("name", f"step-{index + 1}")): step for index, step in enumerate(base_steps)}
    candidate_by_name = {str(step.get("name", f"step-{index + 1}")): step for index, step in enumerate(candidate_steps)}
    features: set[str] = {"mutation-type:" + variant.mutation_type}
    targets: set[str] = set()

    for name, original in base_by_name.items():
        changed = candidate_by_name.get(name)
        if changed is None:
            targets.add(name)
            features.add(f"step-removed:{name}:{original.get('method', '?')}:{original.get('path', '')}")
            continue
        if original.get("method") != changed.get("method") or original.get("path") != changed.get("path"):
            targets.add(name)
            features.add(f"operation:{name}:{changed.get('method', '?')}:{changed.get('path', '')}")
        if original.get("capture", {}) != changed.get("capture", {}):
            targets.add(name)
            features.add(f"capture:{name}:{_sha256_text(_canonical(changed.get('capture', {})))[:12]}")
        original_body_present = "body" in original
        changed_body_present = "body" in changed
        try:
            body_changed = _canonical(original.get("body")) != _canonical(changed.get("body"))
        except (TypeError, ValueError, RecursionError):
            body_changed = original.get("body") != changed.get("body")
        if body_changed or original_body_present != changed_body_present:
            targets.add(name)
            for pointer, bucket, fingerprint in _walk_value_differences(
                original.get("body", None), changed.get("body", None)
            ):
                features.add(f"field:{name}:{pointer}:{bucket}:{fingerprint}")

    base_order = [str(step.get("name", f"step-{index + 1}")) for index, step in enumerate(base_steps)]
    candidate_order = [str(step.get("name", f"step-{index + 1}")) for index, step in enumerate(candidate_steps)]
    # Repeated steps are named from their origin; count them as a transition mutation on that origin.
    for candidate_name, step in candidate_by_name.items():
        if candidate_name in base_by_name:
            continue
        origin = next((name for name in base_order if candidate_name.startswith(name[:105] + "-repeat-")), None)
        if origin is not None:
            targets.add(origin)
            features.add(f"transition-repeat:{origin}:{step.get('method', '?')}:{step.get('path', '')}")
        else:
            features.add(f"step-added:{step.get('method', '?')}:{step.get('path', '')}")

    common_order = [name for name in candidate_order if name in base_by_name]
    base_common_order = [name for name in base_order if name in candidate_by_name]
    if common_order != base_common_order:
        for index, name in enumerate(common_order):
            if index < len(base_common_order) and name != base_common_order[index]:
                targets.update((name, base_common_order[index]))
                features.add(f"order:{base_common_order[index]}->{name}")

    if not targets:
        targets.update(base_order)
    return features, targets


def _select_next_variant(
    pending: list[SequenceVariant],
    *,
    base_sequence: Mapping[str, Any],
    attempted_features: set[str],
    category_counts: Mapping[str, int],
    step_interest: Mapping[str, int],
    tie_rank: Mapping[str, float],
) -> tuple[SequenceVariant | None, dict[str, Any]]:
    """Select the highest-scoring pending variant from accumulated execution feedback."""
    if not pending:
        return None, {"score": 0, "reasons": ["candidate queue empty"], "targets": [], "novel_mutation_features": 0}
    best_index = 0
    best_key: tuple[int, float] | None = None
    best_details: dict[str, Any] = {}
    for index, variant in enumerate(pending):
        features, targets = _variant_mutation_features(base_sequence, variant)
        new_features = features - attempted_features
        fresh_target_count = sum(min(3, max(0, step_interest.get(target, 0))) for target in targets)
        unseen_category_bonus = 5 if category_counts.get(variant.mutation_type, 0) == 0 else 0
        underrepresented_category_bonus = max(0, 3 - category_counts.get(variant.mutation_type, 0))
        score = min(12, len(new_features)) * 2 + fresh_target_count * 3 + unseen_category_bonus + underrepresented_category_bonus
        reasons: list[str] = []
        if new_features:
            reasons.append(f"{len(new_features)} unseen mutation feature(s)")
        if fresh_target_count:
            reasons.append(f"targets {len(targets)} step(s) with newly observed response branches")
        if unseen_category_bonus:
            reasons.append("mutation category not yet exercised")
        if not reasons:
            reasons.append("seeded tie-break among remaining candidates")
        key = (score, tie_rank.get(variant.sha256, 0.0))
        if best_key is None or key > best_key:
            best_index, best_key = index, key
            best_details = {
                "score": score,
                "reasons": reasons,
                "targets": sorted(targets),
                "novel_mutation_features": len(new_features),
                "mutation_features": sorted(features),
            }
    selected = pending.pop(best_index)
    return selected, best_details


def _minimize_values(
    sequence: dict[str, Any],
    *,
    target_name: str,
    target_categories: set[str],
    run_candidate,
    trial_budget: int,
) -> tuple[dict[str, Any], int, bool]:
    """Shrink request bodies structurally and at scalar values while preserving the target mismatch."""
    current = copy.deepcopy(sequence)
    trials = 0
    budget_hit = False
    changed_any = True
    while changed_any and trials < trial_budget:
        changed_any = False
        for step_index, step in enumerate(list(current.get("steps", []))):
            if "body" not in step:
                continue
            candidates = _shrink_candidates(step["body"])
            for smaller_body in candidates:
                if trials >= trial_budget:
                    budget_hit = True
                    break
                changed_steps = copy.deepcopy(current["steps"])
                changed_steps[step_index]["body"] = smaller_body
                candidate = _variant_sequence(current, changed_steps, "value-minimized")
                if not _valid_variant(candidate):
                    continue
                if _same_steps_digest(candidate) == _same_steps_digest(current):
                    continue
                trial_report = run_candidate(candidate)
                trials += 1
                if _preserves_target_failure(trial_report, target_name, target_categories):
                    current = candidate
                    changed_any = True
                    break
            if changed_any or budget_hit:
                break
        if budget_hit:
            break
    if trials >= trial_budget and changed_any:
        budget_hit = True
    return current, trials, budget_hit


def run_http_sequence_exploration(
    *,
    reference_url: str,
    candidate_url: str,
    sequence: Mapping[str, Any],
    sequence_sha256: str,
    reset_sequence: Mapping[str, Any],
    reset_sequence_sha256: str,
    seed: int = 0,
    max_cases: int = 40,
    timeout: float = 5.0,
    repeat: int = 1,
    max_output_bytes: int = 100_000,
    request_headers: Sequence[tuple[str, str]] = (),
    response_headers: Sequence[str] = (),
    contract: CompatibilityContract | None = None,
    minimize: bool = False,
    max_findings_to_minimize: int = 3,
    max_minimization_trials: int = 30,
) -> dict[str, Any]:
    """Explore resettable workflow variants and optionally minimize their failures."""
    variants = generate_sequence_variants(sequence, max_cases=max_cases, seed=seed)
    validate_sequence(dict(reset_sequence))
    for label, digest in (("sequence", sequence_sha256), ("reset sequence", reset_sequence_sha256)):
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"{label} SHA-256 must be a 64-character lowercase hexadecimal digest")
    if type(max_findings_to_minimize) is not int or not 0 <= max_findings_to_minimize <= 20:
        raise ValueError("max_findings_to_minimize must be between 0 and 20")
    if type(max_minimization_trials) is not int or not 1 <= max_minimization_trials <= _MAX_MINIMIZATION_TRIALS:
        raise ValueError(f"max_minimization_trials must be between 1 and {_MAX_MINIMIZATION_TRIALS}")

    contract = contract or CompatibilityContract(name="stateful-http-exploration-default", stdout=OutputContract(mode="json"))
    started = time.perf_counter()
    executions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    minimized_count = 0
    minimization_trials_total = 0
    variants_with_differences = 0
    canonical_variants = [variant for variant in variants]

    seen_response_branches: set[str] = set()
    seen_transitions: set[str] = set()
    seen_difference_signatures: set[str] = set()
    step_interest: dict[str, int] = {}
    attempted_mutation_features: set[str] = set()
    mutation_category_counts: dict[str, int] = {}
    tie_rng = random.Random(seed ^ 0x5A17C0DE)
    tie_rank = {item.sha256: tie_rng.random() for item in canonical_variants}
    coverage_by_case: list[dict[str, Any]] = []

    def run_candidate(candidate_sequence: dict[str, Any]) -> dict[str, Any]:
        return run_http_sequence_comparison(
            reference_url=reference_url,
            candidate_url=candidate_url,
            sequence=candidate_sequence,
            sequence_sha256=_sha256_text(_canonical(candidate_sequence)),
            timeout=timeout,
            repeat=repeat,
            max_output_bytes=max_output_bytes,
            request_headers=request_headers,
            response_headers=response_headers,
            contract=contract,
            reset_sequence=reset_sequence,
            reset_sequence_sha256=reset_sequence_sha256,
            include_behavior_coverage=True,
        )

    if canonical_variants:
        variant: SequenceVariant | None = canonical_variants[0]
        pending = list(canonical_variants[1:])
        priority_details: dict[str, Any] = {
            "score": 0, "reasons": ["baseline always executes first"], "targets": [], "novel_mutation_features": 0
        }
    else:
        variant, pending, priority_details = None, [], {}
    case_index = 1

    while variant is not None:
        case_report = run_candidate(variant.sequence)
        case_execution = case_report["executions"][0]
        differences = list(case_execution.get("differences", []))
        digest = variant.sha256
        coverage_raw = case_report.get("behavior_coverage", {})
        new_branches: list[dict[str, Any]] = []
        new_transitions: list[dict[str, Any]] = []
        new_difference_signatures: list[dict[str, Any]] = []

        base_step_names = [str(step.get("name", f"step-{index + 1}")) for index, step in enumerate(sequence.get("steps", []))]

        def normalize_step_name(name: str) -> str:
            for base_name in base_step_names:
                if name == base_name or name.startswith(base_name + "-repeat-"):
                    return base_name
            return name

        for branch in coverage_raw.get("response_branches", []):
            step_name = str(branch.get("step_name", "unnamed"))
            for side in ("reference", "candidate"):
                signature = str(branch.get(f"{side}_signature", ""))
                target_name = normalize_step_name(step_name)
                feature = f"{target_name}:{side}:{signature}"
                if signature and feature not in seen_response_branches:
                    seen_response_branches.add(feature)
                    new_branches.append({"step_name": target_name, "side": side, "signature": signature})
                    step_interest[target_name] = step_interest.get(target_name, 0) + 1
            categories = sorted({str(value) for value in branch.get("differences", [])})
            if categories:
                target_name = normalize_step_name(step_name)
                diff_feature = f"{target_name}:{','.join(categories)}"
                if diff_feature not in seen_difference_signatures:
                    seen_difference_signatures.add(diff_feature)
                    new_difference_signatures.append({"step_name": target_name, "categories": categories})
                    step_interest[target_name] = step_interest.get(target_name, 0) + 2

        for transition in coverage_raw.get("transitions", []):
            step_name = str(transition.get("step_name", "unnamed"))
            side = str(transition.get("side", "unknown"))
            signature = str(transition.get("signature", ""))
            target_name = normalize_step_name(step_name)
            feature = f"{target_name}:{side}:{signature}"
            if signature and feature not in seen_transitions:
                seen_transitions.add(feature)
                new_transitions.append({"step_name": target_name, "side": side, "signature": signature})
                step_interest[target_name] = step_interest.get(target_name, 0) + 1

        mutation_features, mutation_targets = _variant_mutation_features(sequence, variant)
        execution = {
            "case_index": case_index,
            "input_sha256": digest,
            "differences": differences,
            "sequence_name": variant.sequence.get("name"),
            "sequence_step_count": len(variant.sequence["steps"]),
            "mutation_type": variant.mutation_type,
            "mutation_description": variant.description,
            "priority_score": int(priority_details.get("score", 0)),
            "priority_reasons": list(priority_details.get("reasons", [])),
            "priority_targets": list(priority_details.get("targets", [])),
            "novel_mutation_features_at_schedule": int(priority_details.get("novel_mutation_features", 0)),
            "new_response_branch_count": len(new_branches),
            "new_transition_count": len(new_transitions),
            "new_difference_signature_count": len(new_difference_signatures),
        }
        executions.append(execution)
        coverage_by_case.append({
            "case_index": case_index,
            "new_response_branches": new_branches,
            "new_transitions": new_transitions,
            "new_difference_signatures": new_difference_signatures,
        })
        attempted_mutation_features.update(mutation_features)
        mutation_category_counts[variant.mutation_type] = mutation_category_counts.get(variant.mutation_type, 0) + 1

        if case_report["findings"]:
            variants_with_differences += 1
            finding = copy.deepcopy(case_report["findings"][0])
            finding["case_index"] = case_index
            finding["input_sha256"] = digest
            finding["input"] = _canonical(variant.sequence)
            finding["sequence_definition"] = copy.deepcopy(variant.sequence)
            finding["sequence_file_sha256"] = sequence_sha256
            finding["source_sequence_sha256"] = sequence_sha256
            finding["exploration_variant_sha256"] = digest
            finding["sequence_canonical_sha256"] = _sha256_text(_canonical(variant.sequence))
            finding["mutation_type"] = variant.mutation_type
            finding["mutation_description"] = variant.description
            finding["exploration_case_index"] = case_index
            finding["minimized"] = False
            finding["minimization_trials"] = 0
            finding["minimization_limit_reached"] = False

            target = _target_failure(finding)
            if minimize and minimized_count < max_findings_to_minimize and target:
                target_name, target_categories = target
                step_budget = max(1, (max_minimization_trials * 2) // 3)
                step_minimized, step_trials, step_budget_hit = _minimize_steps(
                    variant.sequence,
                    target_name=target_name,
                    target_categories=target_categories,
                    run_candidate=run_candidate,
                    trial_budget=step_budget,
                )
                remaining_budget = max(0, max_minimization_trials - step_trials)
                value_minimized, value_trials, value_budget_hit = _minimize_values(
                    step_minimized,
                    target_name=target_name,
                    target_categories=target_categories,
                    run_candidate=run_candidate,
                    trial_budget=remaining_budget,
                )
                trials = step_trials + value_trials
                budget_hit = (step_budget_hit and remaining_budget == 0) or (
                    value_budget_hit and trials >= max_minimization_trials
                )
                minimization_trials_total += trials
                finding["minimization_trials"] = trials
                finding["minimization_limit_reached"] = budget_hit
                finding["minimization_phase_trials"] = {
                    "step_deletion": step_trials,
                    "json_body_shrinking": value_trials,
                    "step_phase_budget": step_budget,
                }

                original_step_digest = _same_steps_digest(variant.sequence)
                minimized_step_digest = _same_steps_digest(value_minimized)
                if minimized_step_digest != original_step_digest:
                    minimized_report = run_candidate(value_minimized)
                    if minimized_report["findings"] and _preserves_target_failure(
                        minimized_report, target_name, target_categories
                    ):
                        original_steps_by_name = {
                            str(item.get("name", f"step-{index + 1}")): item
                            for index, item in enumerate(variant.sequence["steps"])
                        }
                        minimized_steps_by_name = {
                            str(item.get("name", f"step-{index + 1}")): item
                            for index, item in enumerate(value_minimized["steps"])
                        }
                        bodies_shrunk = any(
                            name in minimized_steps_by_name
                            and _canonical(original_step.get("body")) != _canonical(minimized_steps_by_name[name].get("body"))
                            for name, original_step in original_steps_by_name.items()
                        )
                        finding["original_sequence_definition"] = copy.deepcopy(variant.sequence)
                        finding["original_sequence_canonical_sha256"] = _sha256_text(_canonical(variant.sequence))
                        finding["sequence_definition"] = value_minimized
                        finding["sequence_name"] = value_minimized.get("name")
                        finding["sequence_canonical_sha256"] = _sha256_text(_canonical(value_minimized))
                        finding["input"] = _canonical(value_minimized)
                        finding["input_sha256"] = _sha256_text(finding["input"])
                        finding["step_results"] = minimized_report["findings"][0]["step_results"]
                        finding["differences"] = minimized_report["findings"][0]["differences"]
                        finding["minimized"] = True
                        finding["minimization"] = {
                            "step_count_before": len(variant.sequence["steps"]),
                            "step_count_after": len(value_minimized["steps"]),
                            "request_bodies_shrunk": bodies_shrunk,
                            "strategy": "step deletion followed by JSON body structural/scalar shrinking",
                        }
                        minimized_count += 1
                else:
                    finding["minimization_target_step"] = target_name
            findings.append(finding)

        variant, priority_details = _select_next_variant(
            pending,
            base_sequence=sequence,
            attempted_features=attempted_mutation_features,
            category_counts=mutation_category_counts,
            step_interest=step_interest,
            tie_rank=tie_rank,
        )
        case_index += 1
    elapsed = time.perf_counter() - started
    canonical_base = _canonical(sequence)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": "TwinCheck",
        "tool_version": __version__,
        "reference_command": f"HTTP EXPLORE {reference_url}",
        "candidate_command": f"HTTP EXPLORE {candidate_url}",
        "strategy": "stateful-http-exploration",
        "seed": seed,
        "repeat": repeat,
        "max_output_bytes": max_output_bytes,
        "working_directory": None,
        "compatibility_contract": contract.to_dict(),
        "compatibility_contract_sha256": contract.sha256,
        "comparison_policy": {"status": True, "json_body": True, "content_type": True},
        "input_source": "stateful-http-exploration",
        "sequence": {
            "name": sequence.get("name", "unnamed-sequence"),
            "schema_version": sequence.get("schema_version", 1),
            "step_count": len(sequence["steps"]),
            "source_sha256": sequence_sha256,
            "canonical_sha256": _sha256_text(canonical_base),
            "definition_included_in_findings": True,
        },
        "state_reset": {
            "enabled": True,
            "sequence_sha256": reset_sequence_sha256,
            "canonical_sha256": _sha256_text(_canonical(reset_sequence)),
            "sequence_definition": copy.deepcopy(dict(reset_sequence)),
            "performed_before_each_variant_and_minimization_trial": True,
            "reset_responses_recorded": False,
            "health_check": {
                "configured": "health" in reset_sequence,
                "verification_mode": "explicit-json-pointer-assertions" if "health" in reset_sequence else "status-only",
                "verified_before_each_variant": "health" in reset_sequence,
                "verified_before_each_minimization_trial": "health" in reset_sequence,
                "assertion_pointers": [item["pointer"] for item in reset_sequence["health"]["assertions"]] if "health" in reset_sequence else [],
            },
        },
        "exploration": {
            "algorithm_version": 2,
            "scheduler": "feedback-guided priority queue over a bounded seeded candidate pool",
            "candidate_count": len(variants),
            "seed": seed,
            "mutation_types": sorted({variant.mutation_type for variant in variants}),
            "mutations": [
                {"case_index": item["case_index"], "type": item["mutation_type"], "description": item["mutation_description"]}
                for item in executions
            ],
            "minimization_enabled": minimize,
            "max_findings_to_minimize": max_findings_to_minimize if minimize else 0,
            "max_minimization_trials": max_minimization_trials if minimize else 0,
            "minimization_trials_total": minimization_trials_total,
            "minimization_strategy": "step deletion followed by JSON body structural/scalar shrinking",
            "mutation_category_counts": dict(sorted(mutation_category_counts.items())),
            "step_interest": dict(sorted(step_interest.items())),
            "coverage_summary": {
                "unique_response_branches": len(seen_response_branches),
                "unique_adjacent_transitions": len(seen_transitions),
                "unique_difference_signatures": len(seen_difference_signatures),
            },
            "coverage_by_case": coverage_by_case,
        },
        "http_adapter": {
            "mode": "stateful-http-exploration",
            "cookies_persist_within_each_target_sequence": True,
            "cookie_jars_shared_between_targets": False,
            "request_header_values_recorded": False,
            "remote_hosts_allowed": False,
            "redirects_followed": False,
        },
        "cases_requested": max_cases,
        "cases_executed": len(executions),
        "timeout_seconds": timeout,
        "minimization_enabled": minimize,
        "executions": executions,
        "elapsed_seconds": round(elapsed, 6),
        "findings": findings,
        "summary": {
            "differences_found": len(findings),
            "cases_with_differences": variants_with_differences,
            "minimized_findings": minimized_count,
            "unstable_reference_findings": sum(1 for item in findings if "reference_unstable" in item["differences"]),
            "unstable_candidate_findings": sum(1 for item in findings if "candidate_unstable" in item["differences"]),
            "truncated_output_findings": sum(1 for item in findings if "output_truncated" in item["differences"]),
            "output_limit_findings": sum(1 for item in findings if "output_limit_exceeded" in item["differences"]),
            "invalid_json_findings": sum(1 for item in findings if any(str(value).endswith("_invalid_json") for value in item["differences"])),
            "steps_with_differences": sum(
                1 for finding in findings for step in finding.get("step_results", []) if step.get("differences")
            ),
        },
        "limitations": [
            "Exploration is deterministic for a given sequence, seed, and version, but mutates request values and sequence structure only within the documented mutation strategy.",
            "A user-provided reset sequence is required and is executed before every variant and minimization trial; this is only as reliable as the service's reset implementation.",
            "Only adjacent steps without direct capture dependencies are reordered; stateful semantics outside capture dependencies cannot be inferred statically.",
            "The feedback scheduler ranks a bounded pre-generated mutation pool; it does not synthesize new mutation operators from runtime traces.",
            "Coverage uses value-free hashes of response status/content type/body shape and adjacent response transitions; it is not source-code branch coverage.",
            "Minimization removes steps, then tries smaller JSON bodies/scalar values while preserving a selected difference category at the same named step.",
            "Only loopback targets are allowed. TwinCheck is not a sandbox and explored requests may create, update, or delete local data.",
        ],
    }
    return report
