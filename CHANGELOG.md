# Changelog

## 0.11.0a1 - Supported public Python API v1 (alpha)

- Expose a versioned Python API for command-line differential comparisons, compatibility contracts, and JSON/JUnit report output.
- Re-export the documented API symbols at the package root and define API_VERSION = 1 as the explicit public compatibility marker.
- Add API compatibility tests for exports, deterministic generated-case comparison, contract loading, serialization and report writers.
- Add a clean-wheel API smoke test and require the public API documentation and tests in the source archive.
- Document which Python imports are supported, how breaking API changes are versioned, and which HTTP workflows remain CLI-only.

This remains pre-1.0 software. API v1 is an explicit compatibility commitment for the documented exports, not a guarantee for internal modules, every report field, or every CLI option.

## 0.10.0a1 - Observation-driven stateful exploration (alpha)

- Add an opt-in adaptive exploration mode that generates paired scalar-boundary candidates after newly observed response branches, adjacent transitions, or difference signatures.
- Preserve static seeded exploration as the default and record the algorithm version, generation rationale, selection rationale, candidate counts, budget and stop reason.
- Add a bounded wall-clock start gate alongside case, timeout, output and minimization-trial limits. Each reset-backed candidate/minimization workflow continues to use explicit reset and health semantics.
- Add an end-to-end test where adaptive exploration finds a two-field interaction defect that static exploration misses under the same two-case budget.
- Add a repeatable static-vs-adaptive comparison script for a pinned synthetic corpus fixture and run it in the Linux/Windows CI matrix.
- Document that the heuristic is not general state-machine learning and that response-shape novelty is not source-code coverage.
- Add distribution validation that builds a wheel and source archive, checks metadata, and installs the wheel in an isolated environment outside the checkout.
- Add a manual release-candidate workflow and an explicit pre-1.0 CLI/schema/Python API compatibility policy; the workflow does not publish to PyPI.
- Use SPDX-style PEP 639 license metadata and include the license file explicitly in built distributions.

This remains an alpha. The comparison is fixture-only and is not a general performance or superiority claim. An in-flight workflow can finish after the wall-clock deadline, bounded by the remaining per-request timeout and sequence limits.

## 0.9.0a1 - Reproducible stateful evidence (alpha)

- Add a versioned five-case synthetic corpus: declared volatile-ID control, cart total drift, stateful read-ordering defect, idempotency/retry defect, and a reset-health guard that must block a stale target.
- Add `python benchmarks/verify_stateful_corpus.py` to check pinned fixture hashes, validate the corpus and project schemas, execute expected cases, inspect safe difference pointers, prove minimization preserves a named mismatch, export/replay a pack, and reject tampering.
- Add value-free per-step explanations with status/content-type metadata, the active comparison contract rules, and bounded safe JSON Pointer paths instead of duplicate field values.
- Expand CI to Linux/Python 3.11, 3.12 and 3.13 plus Windows/Python 3.11; upload synthetic corpus evidence as a GitHub Actions artifact.
- Keep schema validation in the optional `test` extra; the core library remains dependency-free.

This remains an alpha. The corpus is a deterministic correctness fixture, not a performance benchmark or an indication of coverage-guided testing. The synthetic API does not model distributed state, real databases, or concurrent payment processing.

## 0.8.0a1 - Verifiable stateful regression workflows (alpha)

- Add an optional versioned reset-health contract to stateful sequences. After every configured reset, TwinCheck makes a separate read-only GET request and checks explicit scalar JSON Pointer assertions on both local targets before running the tested workflow.
- Record whether reset checking was status-only or assertion-verified. Health summaries retain assertion paths and pass/fail metadata, not observed response values.
- Add explicit `depends_on` metadata to stateful steps and reject dependencies that are duplicated, implicit, unknown, or ordered after their consumer.
- Prevent the bounded adjacent-swap explorer from deliberately reversing directly declared dependencies.
- Add a versioned synthetic stateful regression corpus, a broken-reset negative control, and reproducibility instructions.
- Add regression coverage for a reset endpoint that returns 200 without clearing state and for invalid dependency ordering.

This remains an alpha. A health contract verifies only the declared assertions, not all hidden state. Loopback-only HTTP targeting is not a sandbox. Instrumented coverage, dynamically generated mutation operators, and broad real-world benchmarking remain future work.

## 0.7.0a1 - Portable stateful regression packs (alpha work in progress)

- Add `export-http-sequence-pack` to save one stateful finding as a regression pack containing the request sequence, optional reset workflow, and pinned compatibility contract.
- Add `replay-http-sequence-pack` to replay the pack against explicit loopback targets, with reset-before-repeat behavior and a required side-effect acknowledgement.
- Exclude response traces and request-header values from pack contents; provide authentication headers only at replay time.
- Verify file and canonical hashes before replay and refuse to overwrite existing export destinations.
- Add regression tests and a versioned pack-manifest schema.

This remains an alpha. A successful reset status cannot prove all hidden service state was cleared. Use disposable local services and synthetic data. GitHub publication and the complete Python-version CI matrix remain pending verification.

## 0.6.0a1 - Feedback-guided stateful exploration

- Add value-free response-branch signatures using HTTP status, content type and JSON response shape, plus adjacent transition fingerprints.
- Execute the baseline first, then prioritize a seeded bounded candidate queue using uncovered mutation features, category balance and steps that recently exposed new response behavior.
- Record per-case priority scores/reasons, novel response branches/transitions, difference signatures and aggregate coverage counts in exploration reports.
- Extend minimization from step deletion to structural JSON shrinking (remove fields/items) and scalar simplification, with the same reset-backed failure-preservation check and a shared trial budget.
- Keep normal stateful comparison reports unchanged unless coverage capture is explicitly requested by the exploration engine; signatures do not store response values.
- Document the feedback model and its limits; bump alpha version to `0.6.0a1`.

This remains an alpha. The scheduler ranks a bounded pre-generated candidate pool; it does not synthesize arbitrary mutations from runtime traces. Response-shape fingerprints are not code coverage, and reset success still depends on the user's reset workflow actually clearing the relevant state.

## 0.5.0a1 - Transition-aware stateful workflow exploration

- Add `explore-http-sequence` to generate reproducible JSON body boundary variants, adjacent step reorderings, step removals, and duplicate-step transitions.
- Require a user-authored reset workflow for every test variant and minimization trial; stop before the candidate workflow if either target's reset step fails or is not 2xx.
- Add bounded step-level delta debugging that preserves a selected mismatch category at the same named step.
- Store the mutation metadata, reset workflow definition and hashes, and minimized sequence so findings can be replayed with `replay-http-sequence`.
- Allow ordinary `compare-http-sequence` runs to opt into reset-before-repeat semantics.
- Extend test services, CLI validation, examples and regression coverage for deterministic exploration and faithful replay.

This is still an alpha. The reset endpoint is user-defined and trusted; a 2xx response cannot prove a service has fully reset. The mutator only explores the documented set of local mutations, and minimization removes steps rather than minimizing individual values. Run only against loopback test services using synthetic data.

## 0.4.0a1 - Stateful HTTP compatibility workflows

- Add `compare-http-sequence` for bounded, user-authored multi-request workflows against two loopback HTTP implementations.
- Support response-value capture using JSON Pointer and safe interpolation into later request paths and JSON bodies.
- Preserve independent cookie jars within each target workflow and reset the jars between repeats; redirects remain disabled and proxy environment variables are ignored.
- Include source and canonical sequence hashes, source workflow definition, request-body hashes, per-step observations, and pinpointed differences in reports.
- Add `replay-http-sequence` for replaying a saved finding against explicitly supplied loopback targets; require `--allow-side-effects` and preserve the original compatibility contract.
- Add an example cart service, workflow and contract; add validation, capture, cookie, mismatch and replay tests.

This is an alpha milestone. The workflow is authored explicitly; TwinCheck does not automatically discover state transitions. Request bodies and response observations are part of failure evidence, so workflows must not contain real secrets or customer data. The adapter is not a sandbox.

## 0.3.0a1 - Structured inputs and local HTTP adapter

- Add deterministic JSON Schema-guided request generation, including local JSON Pointer `$ref`, objects, arrays, enums/constants, common scalar constraints, and fail-closed diagnostics for unsupported validation keywords.
- Add `twincheck compare --schema` to drive existing command-line targets with schema-generated JSON inputs and record schema SHA-256 provenance.
- Add `twincheck compare-http` to compare two loopback HTTP implementations using schema-generated JSON request bodies.
- Compare HTTP status, JSON response bodies, and `content-type` by default; allow an explicit response-header allowlist and use the existing versioned compatibility contract for JSON Pointer ignores.
- Keep request header values out of reports, reject non-loopback HTTP targets, and add runnable quote-API examples.
- Add schema generator and HTTP adapter tests; no runtime dependencies added.

This is an alpha increment. JSON Schema generation implements a documented subset rather than the full specification. HTTP mode currently uses a fixed path and request JSON body; it is not a security sandbox or a general network scanner.

## 0.2.0a1 - Development alpha

- Add repeated-run instability detection with per-run evidence for findings.
- Add bounded output retention using file-backed capture and output-limit reporting.
- Add `twincheck replay` to rerun a finding's exact input using explicitly supplied commands.
- Add JUnit XML export with one testcase per executed input.
- Add a versioned JSON Schema for evidence reports.
- Expand README, architecture, threat-model, design-decision and benchmark documentation.
- Make the default per-process timeout more tolerant for slower machines and CI.

This remains an alpha: the runner is not a sandbox, performance has not been benchmarked against mature fuzzing tools, and broad protocol/binary adapters are not implemented.

## 0.1.0 - Initial prototype

- Add deterministic input generation for mixed, text, integer and JSON-like inputs.
- Add shell-free CLI execution with stdin and `{input}` argument support.
- Compare stdout, stderr, exit code, and timeout behavior.
- Add bounded delta-debugging input minimization.
- Add JSON reports, examples, standard-library tests, CI and project documentation.
