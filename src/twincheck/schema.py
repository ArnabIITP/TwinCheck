"""Deterministic, dependency-free sample generation from a JSON Schema subset.

This is a generator, not a full JSON Schema validator. It supports the common
object/array/string/number/boolean/null constraints used to exercise JSON APIs,
local ``$ref`` pointers, enums, constants, and ``anyOf``/``oneOf``. Unsupported
validation keywords fail closed so a schema is not silently treated as fully
honored when it is not.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
import string
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_MAX_SCHEMA_BYTES = 1 * 1024 * 1024
_MAX_DEPTH = 32
_MAX_ARRAY_ITEMS = 100
_MAX_OBJECT_PROPERTIES = 100
_MAX_STRING_LENGTH = 4096
_MAX_GENERATED_INPUT_BYTES = 1 * 1024 * 1024
_MAX_TOTAL_GENERATED_BYTES = 50 * 1024 * 1024
_MAX_GENERATED_CASES = 10000

_ANNOTATIONS = {
    "$schema", "$id", "$anchor", "$comment", "$defs", "definitions",
    "title", "description", "default", "examples", "deprecated",
    "readOnly", "writeOnly", "example",
}
_SUPPORTED = {
    "$ref", "type", "enum", "const", "anyOf", "oneOf", "allOf",
    "properties", "required", "additionalProperties", "minProperties",
    "maxProperties", "items", "prefixItems", "minItems", "maxItems",
    "uniqueItems", "minLength", "maxLength", "pattern", "format",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "minContains", "maxContains", "contains", "not",
    "if", "then", "else", "dependentRequired", "dependentSchemas",
    "patternProperties", "propertyNames", "unevaluatedProperties",
    "unevaluatedItems",
}
_UNSUPPORTED_VALIDATORS = {
    "allOf", "contains", "minContains", "maxContains", "not", "if", "then",
    "else", "dependentRequired", "dependentSchemas", "patternProperties",
    "propertyNames", "unevaluatedProperties", "unevaluatedItems",
}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value!r}")


@dataclass(frozen=True)
class JsonSchemaDocument:
    schema: dict[str, Any]
    sha256: str
    title: str | None = None


def load_json_schema(path: str | Path) -> JsonSchemaDocument:
    """Load and hash a bounded local UTF-8 JSON Schema document."""
    source = Path(path)
    if source.stat().st_size > _MAX_SCHEMA_BYTES:
        raise ValueError("JSON Schema exceeds 1 MiB")
    try:
        raw = source.read_bytes()
        if len(raw) > _MAX_SCHEMA_BYTES:
            raise ValueError("JSON Schema exceeds 1 MiB")
        text = raw.decode("utf-8")
        decoded = json.loads(text, parse_constant=_reject_json_constant)
    except UnicodeDecodeError as exc:
        raise ValueError("JSON Schema must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON Schema JSON: {exc}") from exc
    except ValueError as exc:
        if str(exc).startswith("JSON Schema exceeds"):
            raise
        raise ValueError(f"invalid JSON Schema JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError("JSON Schema is nested too deeply") from exc
    if not isinstance(decoded, dict):
        raise ValueError("JSON Schema root must be an object")
    return JsonSchemaDocument(
        schema=decoded,
        sha256=hashlib.sha256(raw).hexdigest(),
        title=decoded.get("title") if isinstance(decoded.get("title"), str) else None,
    )


def generate_schema_inputs(
    schema: dict[str, Any],
    *,
    count: int,
    seed: int = 0,
) -> list[str]:
    """Generate deterministic, de-duplicated JSON text instances.

    Boundary values are sampled intentionally alongside interior values. If a
    schema's finite domain has fewer values than requested, fewer unique cases
    may be returned; the caller should report the actual case count.
    """
    if count < 1:
        raise ValueError("schema sample count must be at least 1")
    if count > _MAX_GENERATED_CASES:
        raise ValueError(f"schema sample count exceeds the {_MAX_GENERATED_CASES:,}-case safety limit")
    if not isinstance(schema, dict):
        raise ValueError("JSON Schema root must be an object")
    try:
        _check_schema(schema, path="#")
    except RecursionError as exc:
        raise ValueError("JSON Schema nesting exceeds the generator's safe validation limit") from exc
    rng = random.Random(seed)
    output: list[str] = []
    seen: set[str] = set()
    total_bytes = 0
    attempts = 0
    max_attempts = max(30, count * 25)
    while len(output) < count and attempts < max_attempts:
        attempts += 1
        sample = _sample(schema, schema, rng, depth=0, refs=frozenset(), sample_index=attempts)
        if not _matches(schema, sample, schema, depth=0):
            continue
        try:
            encoded = json.dumps(sample, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"generated value is not valid JSON: {exc}") from exc
        encoded_size = len(encoded.encode("utf-8"))
        if encoded_size > _MAX_GENERATED_INPUT_BYTES:
            raise ValueError("generated JSON input exceeds 1 MiB; reduce schema string/array/object bounds")
        if encoded not in seen:
            if total_bytes + encoded_size > _MAX_TOTAL_GENERATED_BYTES:
                raise ValueError("generated JSON inputs exceed the 50 MiB total payload limit; reduce --cases or schema bounds")
            seen.add(encoded)
            output.append(encoded)
            total_bytes += encoded_size
    if not output:
        raise ValueError("schema did not yield any JSON samples")
    return output


def _check_schema(schema: Any, *, path: str) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"schema at {path} must be an object")
    unknown = set(schema) - _ANNOTATIONS - _SUPPORTED
    if unknown:
        raise ValueError(f"unsupported JSON Schema keyword(s) at {path}: {', '.join(sorted(unknown))}")
    unsupported = set(schema) & _UNSUPPORTED_VALIDATORS
    if unsupported:
        raise ValueError(
            f"unsupported JSON Schema constraint(s) at {path}: {', '.join(sorted(unsupported))}; "
            "simplify the schema or pre-generate a corpus for this case"
        )
    for field in ("properties", "$defs", "definitions"):
        nested = schema.get(field)
        if nested is not None:
            if not isinstance(nested, dict):
                raise ValueError(f"{path}/{field} must be an object")
            for name, child in nested.items():
                _check_schema(child, path=f"{path}/{field}/{_escape(name)}")
    if "items" in schema:
        if isinstance(schema["items"], dict):
            _check_schema(schema["items"], path=f"{path}/items")
        elif not isinstance(schema["items"], bool):
            raise ValueError(f"{path}/items must be a boolean or schema object")
    if "prefixItems" in schema:
        if not isinstance(schema["prefixItems"], list):
            raise ValueError(f"{path}/prefixItems must be an array")
        for index, child in enumerate(schema["prefixItems"]):
            _check_schema(child, path=f"{path}/prefixItems/{index}")
    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        _check_schema(schema["additionalProperties"], path=f"{path}/additionalProperties")
    for field in ("anyOf", "oneOf"):
        if field in schema:
            choices = schema[field]
            if not isinstance(choices, list) or not choices:
                raise ValueError(f"{path}/{field} must be a non-empty array")
            for index, child in enumerate(choices):
                _check_schema(child, path=f"{path}/{field}/{index}")
    if "type" in schema:
        valid_types = {"object", "array", "string", "number", "integer", "boolean", "null"}
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not types or any(not isinstance(item, str) or item not in valid_types for item in types):
            raise ValueError(f"{path}/type must be a supported JSON Schema type or non-empty type array")
    for field in ("required",):
        if field in schema and (not isinstance(schema[field], list) or any(not isinstance(v, str) for v in schema[field])):
            raise ValueError(f"{path}/{field} must be an array of strings")
    for field in ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"):
        if field in schema and (type(schema[field]) is not int or schema[field] < 0):
            raise ValueError(f"{path}/{field} must be a non-negative integer")
    if "format" in schema and not isinstance(schema["format"], str):
        raise ValueError(f"{path}/format must be a string")
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str):
            raise ValueError(f"{path}/pattern must be a string")
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            raise ValueError(f"invalid regular expression at {path}/pattern: {exc}") from exc
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ValueError(f"{path}/enum must be a non-empty array")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], (bool, dict)):
        raise ValueError(f"{path}/additionalProperties must be a boolean or schema object")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise ValueError(f"{path}/uniqueItems must be a boolean")
    if "multipleOf" in schema:
        raw_multiple = schema["multipleOf"]
        if isinstance(raw_multiple, bool) or not isinstance(raw_multiple, (int, float)):
            raise ValueError(f"{path}/multipleOf must be numeric")
        try:
            decimal_multiple = Decimal(str(raw_multiple))
            if not decimal_multiple.is_finite() or decimal_multiple <= 0:
                raise ValueError(f"{path}/multipleOf must be finite and greater than zero")
        except InvalidOperation as exc:
            raise ValueError(f"{path}/multipleOf must be numeric") from exc
    for field in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if field in schema:
            raw_bound = schema[field]
            if isinstance(raw_bound, bool) or not isinstance(raw_bound, (int, float)):
                raise ValueError(f"{path}/{field} must be numeric")
            try:
                decimal_bound = Decimal(str(raw_bound))
                if not decimal_bound.is_finite():
                    raise ValueError(f"{path}/{field} must be finite")
            except InvalidOperation as exc:
                raise ValueError(f"{path}/{field} must be numeric") from exc



def _json_equal(left: Any, right: Any) -> bool:
    """JSON value equality, keeping booleans distinct from numeric 0/1."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except InvalidOperation:
            return False
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return isinstance(left, list) and isinstance(right, list) and len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return type(left) is type(right) and left == right


def _matches(schema: dict[str, Any], value: Any, root: dict[str, Any], *, depth: int) -> bool:
    """Validate generated instances against the supported constraint subset."""
    if depth > _MAX_DEPTH:
        return False
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            return False
        try:
            target = _resolve_pointer(root, reference)
        except ValueError:
            return False
        siblings = {key: child for key, child in schema.items() if key != "$ref"}
        return _matches(target, value, root, depth=depth + 1) and _matches(siblings, value, root, depth=depth + 1)
    if "const" in schema and not _json_equal(value, schema["const"]):
        return False
    if "enum" in schema and not any(_json_equal(value, choice) for choice in schema["enum"]):
        return False
    if "anyOf" in schema and not any(_matches(branch, value, root, depth=depth + 1) for branch in schema["anyOf"]):
        return False
    if "oneOf" in schema and sum(_matches(branch, value, root, depth=depth + 1) for branch in schema["oneOf"]) != 1:
        return False
    types = schema.get("type")
    if types is not None:
        types = types if isinstance(types, list) else [types]
        def type_match(name: str) -> bool:
            if name == "object": return isinstance(value, dict)
            if name == "array": return isinstance(value, list)
            if name == "string": return isinstance(value, str)
            if name == "integer":
                return (isinstance(value, int) and not isinstance(value, bool)) or (
                    isinstance(value, float) and math.isfinite(value) and value.is_integer()
                )
            if name == "number": return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
            if name == "boolean": return isinstance(value, bool)
            if name == "null": return value is None
            return False
        if not any(type_match(name) for name in types):
            return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not all(key in value for key in required):
            return False
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            return False
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            return False
        additional = schema.get("additionalProperties", True)
        for key, child in value.items():
            if key in properties:
                if not _matches(properties[key], child, root, depth=depth + 1):
                    return False
            elif additional is False:
                return False
            elif isinstance(additional, dict) and not _matches(additional, child, root, depth=depth + 1):
                return False
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return False
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return False
        if schema.get("uniqueItems", False):
            if any(_json_equal(value[i], value[j]) for i in range(len(value)) for j in range(i + 1, len(value))):
                return False
        prefix = schema.get("prefixItems", [])
        items = schema.get("items", {})
        for index, child in enumerate(value):
            child_schema = prefix[index] if index < len(prefix) else items
            if child_schema is False:
                return False
            if child_schema not in (True, False) and isinstance(child_schema, dict) and not _matches(child_schema, child, root, depth=depth + 1):
                return False
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return False
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return False
        if "pattern" in schema and not re.search(schema["pattern"], value):
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = Decimal(str(value))
        if "minimum" in schema and number < Decimal(str(schema["minimum"])):
            return False
        if "maximum" in schema and number > Decimal(str(schema["maximum"])):
            return False
        if "exclusiveMinimum" in schema and number <= Decimal(str(schema["exclusiveMinimum"])):
            return False
        if "exclusiveMaximum" in schema and number >= Decimal(str(schema["exclusiveMaximum"])):
            return False
        if "multipleOf" in schema and number % Decimal(str(schema["multipleOf"])) != 0:
            return False
    return True


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _resolve_pointer(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#"):
        raise ValueError(f"remote JSON Schema reference {reference!r} is not supported; use local #/ pointers")
    fragment = reference[1:]
    if fragment == "":
        return root
    if not fragment.startswith("/"):
        raise ValueError(f"unsupported JSON Schema anchor reference {reference!r}; use local #/ pointers")
    current: Any = root
    for segment in fragment[1:].split("/"):
        segment = segment.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or segment not in current:
            raise ValueError(f"unresolved local JSON Schema reference {reference!r}")
        current = current[segment]
    if not isinstance(current, dict):
        raise ValueError(f"JSON Schema reference {reference!r} does not point to a schema object")
    return current


def _sample(
    schema: dict[str, Any],
    root: dict[str, Any],
    rng: random.Random,
    *,
    depth: int,
    refs: frozenset[str],
    sample_index: int,
) -> Any:
    if depth > _MAX_DEPTH:
        raise ValueError("schema nesting/recursion exceeds the 32-level generation limit")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            raise ValueError("$ref must be a string")
        if reference in refs:
            raise ValueError(f"recursive JSON Schema reference {reference!r} cannot be expanded without a finite bound")
        resolved = _resolve_pointer(root, reference)
        siblings = {key: value for key, value in schema.items() if key != "$ref"}
        combined = dict(resolved)
        combined.update(siblings)
        return _sample(combined, root, rng, depth=depth + 1, refs=refs | {reference}, sample_index=sample_index)
    for composition in ("anyOf", "oneOf"):
        if composition in schema:
            choices = schema[composition]
            choice = choices[sample_index % len(choices)] if sample_index % 2 == 0 else rng.choice(choices)
            return _sample(choice, root, rng, depth=depth + 1, refs=refs, sample_index=sample_index)
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if "enum" in schema:
        return copy.deepcopy(rng.choice(schema["enum"]))

    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        selected_type = raw_type[(sample_index - 1) % len(raw_type)] if sample_index % 2 else rng.choice(raw_type)
    elif isinstance(raw_type, str):
        selected_type = raw_type
    elif "properties" in schema or "required" in schema or "additionalProperties" in schema:
        selected_type = "object"
    elif "items" in schema or "prefixItems" in schema:
        selected_type = "array"
    elif any(key in schema for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf")):
        selected_type = "integer" if sample_index % 2 else "number"
    else:
        selected_type = rng.choice(("object", "array", "string", "integer", "boolean", "null"))

    if selected_type == "object":
        return _sample_object(schema, root, rng, depth=depth, refs=refs, sample_index=sample_index)
    if selected_type == "array":
        return _sample_array(schema, root, rng, depth=depth, refs=refs, sample_index=sample_index)
    if selected_type == "string":
        return _sample_string(schema, rng, sample_index=sample_index)
    if selected_type in {"integer", "number"}:
        return _sample_number(schema, rng, integer=(selected_type == "integer"), sample_index=sample_index)
    if selected_type == "boolean":
        return bool((sample_index + rng.randrange(2)) % 2)
    if selected_type == "null":
        return None
    raise ValueError(f"unsupported schema type {selected_type!r}")


def _sample_object(schema: dict[str, Any], root: dict[str, Any], rng: random.Random, *, depth: int, refs: frozenset[str], sample_index: int) -> dict[str, Any]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("object schema 'properties' must be an object")
    required = schema.get("required", [])
    additional = schema.get("additionalProperties", True)
    if any(key not in properties for key in required) and additional is False:
        raise ValueError("object schema requires a property not declared in properties while additionalProperties is false")
    max_props = min(schema.get("maxProperties", _MAX_OBJECT_PROPERTIES), _MAX_OBJECT_PROPERTIES)
    min_props = schema.get("minProperties", 0)
    if min_props > _MAX_OBJECT_PROPERTIES or len(required) > max_props:
        raise ValueError("object schema property bounds are inconsistent or exceed 100 generated properties")
    if min_props > max_props:
        raise ValueError("object schema minProperties exceeds maxProperties")

    keys = list(properties)
    chosen = set(required)
    for key in keys:
        if key not in chosen and rng.random() < (0.25 if sample_index % 3 else 0.65):
            chosen.add(key)
    if len(chosen) > max_props:
        optional = [key for key in keys if key in chosen and key not in required]
        rng.shuffle(optional)
        while len(chosen) > max_props and optional:
            chosen.remove(optional.pop())
    result: dict[str, Any] = {}
    for index, key in enumerate(keys):
        if key in chosen:
            result[key] = _sample(properties[key], root, rng, depth=depth + 1, refs=refs, sample_index=sample_index + index + 1)
    additional_index = 0
    additional_schema = additional if isinstance(additional, dict) else {}
    for key in required:
        if key not in result:
            result[key] = _sample(additional_schema, root, rng, depth=depth + 1, refs=refs, sample_index=sample_index + len(result) + 1)
    while len(result) < min_props:
        if additional is False:
            remaining = [key for key in keys if key not in result]
            if not remaining:
                raise ValueError("object schema cannot meet minProperties with additionalProperties=false")
            key = remaining[0]
            result[key] = _sample(properties[key], root, rng, depth=depth + 1, refs=refs, sample_index=sample_index + len(result) + 1)
        else:
            key = f"extra_{additional_index}"
            while key in result or key in properties:
                additional_index += 1
                key = f"extra_{additional_index}"
            value_schema = additional if isinstance(additional, dict) else {}
            result[key] = _sample(value_schema, root, rng, depth=depth + 1, refs=refs, sample_index=sample_index + len(result) + 1)
        additional_index += 1
    if additional is not False and len(result) < max_props and rng.random() < 0.15:
        key = f"extra_{sample_index % 7}"
        if key not in result and key not in properties:
            value_schema = additional if isinstance(additional, dict) else {}
            result[key] = _sample(value_schema, root, rng, depth=depth + 1, refs=refs, sample_index=sample_index + 7)
    return result


def _sample_array(schema: dict[str, Any], root: dict[str, Any], rng: random.Random, *, depth: int, refs: frozenset[str], sample_index: int) -> list[Any]:
    minimum = schema.get("minItems", 0)
    maximum = min(schema.get("maxItems", max(minimum, 4)), _MAX_ARRAY_ITEMS)
    if minimum > _MAX_ARRAY_ITEMS or minimum > maximum:
        raise ValueError("array schema minItems/maxItems are inconsistent or exceed the 100-item generation limit")
    length = rng.choice(sorted(set((minimum, min(maximum, minimum + 1), min(maximum, max(minimum, 3)), maximum))))
    if "prefixItems" in schema:
        prefix_items = schema["prefixItems"]
        if length < len(prefix_items):
            length = min(maximum, max(length, len(prefix_items)))
        items_schema = schema.get("items", {})
    else:
        prefix_items = []
        items_schema = schema.get("items", {})
    if items_schema is True:
        items_schema = {}
    elif items_schema is False:
        if minimum > len(prefix_items):
            raise ValueError("array schema minItems cannot be satisfied because items is false")
        length = min(length, len(prefix_items))
    elif not isinstance(items_schema, dict):
        raise ValueError("items must be a boolean or schema object")
    result: list[Any] = []
    signatures: set[str] = set()
    for index in range(length):
        child_schema = prefix_items[index] if index < len(prefix_items) else items_schema
        for attempt in range(30):
            value = _sample(child_schema, root, rng, depth=depth + 1, refs=refs, sample_index=sample_index + index + attempt)
            signature = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if not schema.get("uniqueItems", False) or signature not in signatures:
                result.append(value)
                signatures.add(signature)
                break
        else:
            raise ValueError("could not generate enough unique items for uniqueItems=true")
    return result


def _sample_string(schema: dict[str, Any], rng: random.Random, *, sample_index: int) -> str:
    min_len = schema.get("minLength", 0)
    max_len = min(schema.get("maxLength", max(min_len, 20)), _MAX_STRING_LENGTH)
    if min_len > _MAX_STRING_LENGTH or min_len > max_len:
        raise ValueError("string schema minLength/maxLength are inconsistent or exceed the 4096-character limit")
    length_choices = sorted(set((min_len, min(max_len, min_len + 1), min(max_len, max(min_len, 8)), max_len)))
    length = rng.choice(length_choices)
    format_name = schema.get("format")
    if format_name == "email":
        candidates = ["a@example.com", "test+tc@example.org", "user42@local.test"]
    elif format_name == "uuid":
        candidates = ["123e4567-e89b-12d3-a456-426614174000", "00000000-0000-4000-8000-000000000001"]
    elif format_name == "date":
        candidates = [date(2024, 2, 29).isoformat(), date(2000, 1, 1).isoformat(), "2030-12-31"]
    elif format_name == "date-time":
        candidates = ["2024-02-29T12:34:56Z", "2030-01-01T00:00:00Z"]
    elif format_name == "uri":
        candidates = ["https://example.com/resource", "https://example.org/"]
    elif format_name == "ipv4":
        candidates = ["192.0.2.1", "198.51.100.2", "203.0.113.7"]
    else:
        candidates = ["", "a", "x", "test", "example", "user_123", "-", "abc-123", "A" * max(1, length), "a" * max(1, length)]
    pattern = schema.get("pattern")
    valid: list[str] = []
    for candidate in candidates:
        if not min_len <= len(candidate) <= max_len:
            continue
        if isinstance(pattern, str) and not re.search(pattern, candidate):
            continue
        valid.append(candidate)
    if not valid and isinstance(pattern, str):
        # Handle the common anchored forms such as ^[A-Z0-9]{6,10}$ or ^\d{4}$.
        match = re.fullmatch(r"\^?(\[[^\]]+\]|\\[dws]|[A-Za-z0-9 _-])(?:\{(\d+)(?:,(\d*))?\})?\$?", pattern)
        if match:
            token, lo, hi = match.groups()
            chars = {"\\d": string.digits, "\\w": string.ascii_letters + string.digits + "_", "\\s": " "}
            raw_charset = chars.get(token, token[1:-1] if token.startswith("[") else token)
            if raw_charset in chars.values():
                charset = raw_charset
            else:
                expanded: list[str] = []
                cursor = 0
                while cursor < len(raw_charset):
                    if cursor + 2 < len(raw_charset) and raw_charset[cursor + 1] == "-":
                        start_char, end_char = raw_charset[cursor], raw_charset[cursor + 2]
                        if ord(start_char) <= ord(end_char) and ord(end_char) - ord(start_char) <= 128:
                            expanded.extend(chr(code) for code in range(ord(start_char), ord(end_char) + 1))
                            cursor += 3
                            continue
                    expanded.append(raw_charset[cursor])
                    cursor += 1
                charset = "".join(dict.fromkeys(expanded))
            low = int(lo) if lo is not None else min_len
            high = int(hi) if hi else (int(lo) if lo else max_len)
            low, high = max(low, min_len), min(high, max_len)
            if low <= high and charset:
                length = rng.choice(sorted(set((low, min(high, low + 1), high))))
                generated = "".join(rng.choice(charset) for _ in range(length))
                if re.search(pattern, generated):
                    valid.append(generated)
    if not valid:
        if isinstance(pattern, str):
            raise ValueError(f"cannot synthesize a string for pattern {pattern!r}; add enum/examples or use a simpler pattern")
        # Unknown formats are annotations in JSON Schema, so do not claim to validate them.
        return "" if min_len == 0 else ("x" * min_len)
    picked = rng.choice(valid)
    if not pattern and len(picked) < min_len:
        picked = (picked + ("x" * max(0, min_len - len(picked))))[:max_len]
    if len(picked) > max_len:
        picked = picked[:max_len]
    return picked


def _sample_number(schema: dict[str, Any], rng: random.Random, *, integer: bool, sample_index: int) -> int | float:
    try:
        minimum = Decimal(str(schema["minimum"])) if "minimum" in schema else None
        maximum = Decimal(str(schema["maximum"])) if "maximum" in schema else None
        exclusive_minimum = Decimal(str(schema["exclusiveMinimum"])) if "exclusiveMinimum" in schema else None
        exclusive_maximum = Decimal(str(schema["exclusiveMaximum"])) if "exclusiveMaximum" in schema else None
        multiple = Decimal(str(schema["multipleOf"])) if "multipleOf" in schema else None
    except InvalidOperation as exc:
        raise ValueError(f"numeric JSON Schema bound is invalid: {exc}") from exc
    strict_step = Decimal("1") if integer else Decimal("0.000001")
    lower_bounds = [bound for bound in (minimum, exclusive_minimum + strict_step if exclusive_minimum is not None else None) if bound is not None]
    upper_bounds = [bound for bound in (maximum, exclusive_maximum - strict_step if exclusive_maximum is not None else None) if bound is not None]
    minimum = max(lower_bounds) if lower_bounds else None
    maximum = min(upper_bounds) if upper_bounds else None
    if integer:
        low = math.ceil(minimum) if minimum is not None else -100
        high = math.floor(maximum) if maximum is not None else 100
        if low > high:
            raise ValueError("integer schema has no value satisfying its minimum/maximum bounds")
        if multiple is not None:
            numerator, denominator = multiple.as_integer_ratio()
            step = numerator // math.gcd(numerator, denominator)
            low = math.ceil(low / step) * step
            high = math.floor(high / step) * step
            if low > high:
                raise ValueError("integer schema has no value satisfying multipleOf and its bounds")
        choices = [low, high, min(high, max(low, 0)), min(high, max(low, 1))]
        if low <= 42 <= high:
            choices.append(42)
        return rng.choice(choices) if sample_index % 3 else rng.randint(low, high)
    low = minimum if minimum is not None else Decimal("-100")
    high = maximum if maximum is not None else Decimal("100")
    if low > high:
        raise ValueError("number schema has inconsistent minimum/maximum bounds")
    if multiple is not None:
        low_k = math.ceil(low / multiple)
        high_k = math.floor(high / multiple)
        if low_k > high_k:
            raise ValueError("number schema has no value satisfying multipleOf and its bounds")
        choice = rng.choice([low_k, high_k, min(high_k, max(low_k, 0)), rng.randint(low_k, high_k)])
        result = Decimal(choice) * multiple
    else:
        candidates = [low, high, min(high, max(low, Decimal(0))), min(high, max(low, Decimal(1)))]
        if low <= Decimal("42") <= high:
            candidates.append(Decimal("42"))
        result = rng.choice(candidates) if sample_index % 3 else low + (high - low) * Decimal(str(rng.random()))
    value = float(result)
    if not math.isfinite(value):
        raise ValueError("numeric schema bounds are too large to serialize as JSON")
    return value
