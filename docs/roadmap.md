# Roadmap

This roadmap describes an ambition, not a promise. Features should ship only when their behavior can be tested and documented.

## v0.1 — deterministic process differential testing

- [x] CLI for two command-line programs
- [x] Seeded input generation, corpus support, bounded process execution
- [x] Difference reports, replay, and bounded input minimization

## v0.2 — reproducibility and policy

- [x] JUnit XML and repeated-run instability detection
- [x] Versioned compatibility contracts and contract-pinned counterexample packs
- [x] Bounded output capture and report provenance

## v0.3 — structured inputs and HTTP

- [x] JSON Schema-guided request generation (documented subset)
- [x] Local HTTP request/response comparison

## v0.4 — stateful HTTP workflows

- [x] Multi-step sequences with scalar JSON Pointer captures and templated paths/bodies
- [x] Independent session cookies and replayable step-level response evidence
- [x] Optional reset-before-repeat for explicit sequences

## v0.5 — transition-aware stateful exploration

- [x] Deterministic JSON body boundary mutations
- [x] Adjacent step swaps that preserve direct capture dependencies
- [x] Step removal and step duplication variants
- [x] Required reset workflow before each exploration variant and minimization trial
- [x] Bounded step-level minimization that preserves a selected mismatch at the same named step
- [x] Persist reset definitions and hashes for faithful replay

## v0.6 — response feedback and body minimization

- [x] Track value-free per-step response branch signatures from status, content type, and JSON response shape
- [x] Track adjacent response-transition signatures independently for reference and candidate services
- [x] Prioritize a bounded seeded candidate pool using new response behavior, untried mutation features, and mutation-category balance
- [x] Record priority scores/reasons and per-case new coverage in reports
- [x] Shrink JSON request bodies by deleting fields/items and reducing scalar values while preserving the mismatch

## v0.7 — portable stateful regression workflow (alpha work in progress)

- [x] Export one stateful finding as a sequence pack with its semantic contract pinned
- [x] Include the optional reset workflow and preserve source/canonical hashes
- [x] Validate pack file hashes and sequence structure before replay
- [x] Replay only against explicit loopback targets and require acknowledgement of state-changing requests
- [x] Exclude response observations and request-header values from the exported pack
- [ ] Verify the complete test suite on Python 3.11, 3.12 and 3.13 in GitHub Actions
- [ ] Publish the implementation after the CI matrix is green

## v0.8 — stronger workflow semantics and validation

- [ ] Reset-health verification beyond HTTP status (e.g. explicit reset marker/state fingerprint)
- [ ] Explicit dependency and precondition metadata to improve safe operation ordering
- [ ] Optional adapter-provided/instrumented coverage feedback beyond response-shape signatures
- [ ] Mutation operators generated dynamically from new observations, beyond ranking a bounded pool
- [ ] More representative real-world API regression benchmarks and reproducibility study

## Later — isolation and stable workflows

- [ ] Optional container-backed isolation and platform-specific resource limits; security-sensitive
- [ ] File-system and richer protocol observers with explicit scopes
- [ ] Stable public Python API and backward-compatible report schema
- [ ] Independently reviewed benchmark corpus and security boundaries

## Non-goals

- Claiming formal equivalence of arbitrary programs
- Running untrusted code safely without an isolation backend
- Arbitrary remote API scanning
- Treating a successful reset HTTP status as proof that all hidden service state was reset
