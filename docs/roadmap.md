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

## v0.7 — portable stateful regression workflow

- [x] Export a stateful finding as a sequence pack with its semantic contract pinned
- [x] Include the optional reset workflow and preserve source/canonical hashes
- [x] Validate pack file hashes and sequence structure before replay
- [x] Replay only against explicit loopback targets and require acknowledgement of state-changing requests
- [x] Exclude response observations and request-header values from exported packs
- [x] Verify the core test suite on Python 3.11, 3.12 and 3.13 in GitHub Actions before treating the milestone as release-ready
- [ ] Publish a package only after the release artifact and metadata are reviewed

## v0.8 — evidence quality for stateful regressions

- [x] Optional read-only reset-health contract with explicit scalar JSON Pointer assertions
- [x] Distinguish status-only reset checks from assertion-verified resets in reports
- [x] Explicit named-step dependencies with validation of earlier-step ordering
- [x] Prevent adjacent-swap mutations from reversing directly declared dependencies
- [x] Add a small, versioned synthetic stateful corpus and a deliberately broken reset negative control
- [x] Add a regression test that a supplied request-header secret appears neither in JSON evidence nor the portable stateful pack
- [x] Update the sample cart service, sequence examples, schema, threat model, changelog, and user guide
- [x] Run the fixed corpus end to end through comparison, reset-health verification, pack export, and replay in CI
- [x] Run the full suite and clean-install/CLI/corpus smoke checks on Python 3.11, 3.12 and 3.13 in GitHub Actions

## v0.9 — reproducible stateful evidence

- [x] Pin all corpus sequences, contracts, synthetic service fixture, and schemas with SHA-256 hashes
- [x] Add a clean volatile-field control and fixed response drift, stateful ordering, idempotency/retry, and stale-reset guard cases
- [x] Add a single corpus verification command with expected-outcome checks
- [x] Validate generated reports and regression-pack manifests against the checked-in JSON Schemas
- [x] Verify safe difference paths and secret-free explanatory metadata
- [x] Exercise a seeded minimization and assert that the named mismatch remains reproducible
- [x] Export/replay a pack and test rejection of tampered content
- [x] Add Windows CI alongside the Python 3.11/3.12/3.13 Linux matrix
- [x] Merge after all four CI matrix jobs passed on the PR head

## v0.10 — observation-driven stateful exploration

- [x] Keep static seeded exploration as the unchanged default and make adaptive exploration opt-in
- [x] Define a value-free response feedback model from response-branch, adjacent-transition and difference-signature novelty
- [x] Generate bounded paired body-boundary candidates from a newly observed earlier step into a later workflow transition
- [x] Record algorithm version, generation rationale, selection rationale, candidate counts and stop reason
- [x] Preserve reset-before-candidate/minimization behavior, dependency validation and request/output limits
- [x] Add a synthetic two-field interaction defect that adaptive mode finds but static mode misses under the same two-case execution budget
- [x] Add a fixed-fixture static/adaptive comparison report and run it in Linux/Windows CI
- [x] Document that adaptive feedback is a bounded heuristic, not learned state-machine coverage

## Release readiness

- [x] Document the alpha compatibility promise and distinguish the CLI, versioned file schemas and internal Python modules
- [x] Build one wheel and one source archive with Python packaging tools
- [x] Check distribution metadata and install the built wheel into a clean virtual environment outside the checkout
- [x] Run distribution validation in the Linux/Python 3.11–3.13 and Windows/Python 3.11 CI matrix
- [x] Add a manual release-candidate workflow that uploads verified artifacts without publishing them
- [x] Document the release checklist, source archive inspection and explicit publish approval gate
- [ ] Publish to PyPI only after separate maintainer approval and a final artifact review
- [ ] Establish a stable public Python API before promising API compatibility

## Later — research and expansion, not release blockers

- [ ] Design an adapter protocol for optional instrumentation or coverage feedback; first define its trust and reproducibility contract
- [x] Evaluate observation-driven mutation generation against the fixed seeded candidate pool on a pinned synthetic fixture
- [ ] Add a broader independently reviewable synthetic corpus before attempting external API benchmarks
- [ ] Consider adapters beyond HTTP only after reset, replay, and reporting guarantees have clear interfaces

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
