# JSON Schema-guided input generation

TwinCheck can generate structured JSON inputs with `--schema` for the CLI adapter and `compare-http` for the local HTTP adapter. The generator is deterministic for a pinned TwinCheck version, schema file, seed and requested case count. The report records the exact schema SHA-256 and unique sample count.

This feature is an **input generator with validation for a documented subset**, not a replacement for a complete JSON Schema implementation. It uses only the Python standard library and does not fetch remote references.

## Supported constraints

- Primitive `type` values: `object`, `array`, `string`, `number`, `integer`, `boolean`, and `null`; basic type unions are supported.
- `enum`, `const`, `anyOf` and `oneOf`; generated values are checked against the implemented constraints.
- Objects: `properties`, `required`, `additionalProperties`, `minProperties`, `maxProperties`.
- Arrays: `items`, `prefixItems`, `minItems`, `maxItems`, `uniqueItems`.
- Strings: `minLength`, `maxLength`, simple regex patterns, and sample hints for `email`, `uuid`, `date`, `date-time`, `uri`, and `ipv4` formats.
- Numbers: inclusive/exclusive bounds and `multipleOf`.
- Local JSON Pointer `$ref` references into the same file, including `#/definitions/...` and `#/$defs/...`.
- Common annotation keywords such as `title`, `description`, `default`, `examples`, `deprecated`, and `readOnly` are ignored as annotations.

## Explicit limitations

- Remote `$ref` URLs and `$anchor` reference resolution are not supported. The loader never retrieves a schema over the network.
- `allOf`, `not`, conditional schemas (`if`/`then`/`else`), dependency constraints, `patternProperties`, `propertyNames`, `contains`, `unevaluatedProperties`, and `unevaluatedItems` are rejected.
- Regex synthesis is intentionally narrow. A complex pattern may require `enum`, a supplied corpus, or a simpler pattern.
- Cyclic recursive `$ref` expansion is rejected instead of risking an unbounded generated structure.
- The generator biases values toward boundaries but does not promise complete boundary coverage or exhaustive enumeration.
- A narrow finite schema can yield fewer unique inputs than requested. Inspect `cases_executed` and `input_generation.unique_sample_count` in the report.
- `compare --schema` and `--corpus` cannot be combined in this release.

Unsupported validation keywords produce an actionable error. This is deliberate: silently ignoring a constraint could make a generated request invalid while appearing schema-aware.

## Suggested workflow

1. Pin the schema artifact in version control.
2. Run with a fixed seed and save the JSON report.
3. Review any reported mismatch and export its input through the existing counterexample-pack workflow where suitable.
4. Keep a separate regression corpus for cases the generator cannot express, such as complex regular languages or stateful sequences.
