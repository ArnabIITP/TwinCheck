# Roadmap

This roadmap describes an ambition, not a promise. Features should ship only when their behavior can be tested and documented.

## v0.1 — reliable local differential testing

- [x] CLI for two command-line programs
- [x] Deterministic seed and mixed/text/integer/JSON input strategies
- [x] Optional UTF-8 corpus directory
- [x] Compare stdout, stderr, exit code and timeout behavior
- [x] Output normalization flags
- [x] Bounded delta-debugging minimization
- [x] JSON reports and non-zero exit on findings
- [x] Standard-library test suite and CI workflow

## v0.2 — contract-driven compatibility (current alpha)

- [x] Versioned JSON compatibility contract with strict validation
- [x] Exact-text and structural-JSON output comparison
- [x] RFC 6901 JSON Pointer ignore paths for volatile JSON fields
- [x] Report the normalized contract and SHA-256 fingerprint used for each run
- [x] Apply the same contract to repeated-run signatures and minimization
- [x] Replay a saved finding with explicitly supplied commands
- [x] JUnit XML export for CI systems
- [x] Export counterexamples into a portable manifest+inputs pack, pinned to a contract hash
- [x] Verify pack manifest, case hashes, and contract fingerprint before replay
- [ ] Shell-escaped reproducer command and bounded side-by-side output diff

## v0.3 — structured inputs and domain adapters

- [ ] JSON Schema-driven input generation
- [ ] HTTP request/response adapter for local test services
- [ ] Structured protocol adapter interface
- [ ] Explicit environment-variable comparison policy
- [ ] Optional oracle and custom output-normalizer plugins

## v0.4 — isolation and observability

- [ ] Container-backed isolation backend
- [ ] Resource limits and bounded output capture
- [ ] File-system change observer
- [ ] Reproducibility controls for locale, timezone and environment
- [ ] Optional coverage-guided exploration when an instrumented runtime is available

## v1.0 — trustworthy compatibility workflows

- [ ] Stable versioned report schema and documented API
- [ ] Re-run command for every finding
- [ ] Regression fixtures generated from minimized cases
- [ ] Performance baseline and large-suite benchmarks published with methodology
- [ ] Security review for any sandbox implementation

## Non-goals for the first release

- Claiming formal equivalence of arbitrary programs
- Running untrusted code safely without an isolation backend
- AI-generated findings without successful execution
- Supporting every programming language or binary format before the CLI core is stable
