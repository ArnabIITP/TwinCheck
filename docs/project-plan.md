# TwinCheck — Project Plan

**Status:** v0.1 prototype. **Goal:** make behavioral compatibility testing reproducible and evidence-based.

## 1. Problem

A replacement library, port, parser, or command-line tool can pass ordinary tests while disagreeing with the reference implementation on edge cases. Developers need to discover discrepancies and receive a small input that reproduces each one.

## 2. Target users

- Maintainers of alternative implementations, forks, ports, and compatibility layers.
- Language-runtime and compiler developers comparing behavior across implementations.
- Teams replacing parsers, serializers, command-line tools, or data processors.
- CI engineers who need a repeatable compatibility gate.

## 3. Principles

1. **Execute to verify:** findings arise from real executions, not AI guesses.
2. **Reproducibility first:** preserve seed, exact input, commands, observations, and tool version.
3. **Local by default:** no external service or runtime third-party dependency is required.
4. **Safe claims:** passing sampled cases is not proof of equivalence.
5. **Clear safety boundary:** commands run with the current user's permissions; this is not a sandbox.
6. **Small core, extensible edges:** build a dependable CLI before adding protocol adapters or agents.

## 4. MVP scope (v0.1)

- Python 3.11+ CLI with a compare command.
- Deterministic input generation: mixed, text, integer, and JSON-shaped text strategies.
- Optional local UTF-8 corpus, loaded in stable path order.
- Paired command execution, stdin support, {input} argument substitution, and timeouts.
- Compare stdout, stderr, exit code, and timeout status, with opt-in normalization flags.
- Bounded delta-debugging minimizer for a limited number of findings.
- JSON report containing input, digest, difference categories, process observations, seed, and summary.
- Examples, tests, CI, contribution guidelines, security policy, and MIT license.

## 5. Non-goals for v0.1

- Formal proof of program equivalence.
- Safe execution of untrusted programs.
- Binary analysis, disassembly, or network protocol capture.
- Filesystem/network side-effect observation.
- AI-generated findings without execution evidence.
- Universal language-specific fuzzing.

## 6. Architecture

- src/twincheck/generators.py: seeded test-case generation and corpus loading.
- src/twincheck/runner.py: shell-free process invocation, stdin, timeouts, and observations.
- src/twincheck/compare.py: output normalization, mismatch categories, and minimization.
- src/twincheck/engine.py: orchestrates cases, execution, findings, and report metadata.
- src/twincheck/report.py: JSON serialization and terminal summary.
- src/twincheck/cli.py: argument parsing, validation, output formatting, and exit codes.

Dependencies flow inward: the CLI calls the engine; the engine composes generation, runner, comparison, and reporting.

## 7. Quality gates

- Tests cover deterministic generation, unique requested cases, boundaries, command parsing, stdin, argument substitution, timeouts, normalization, exit codes, minimizer behavior, and report validity.
- CI runs the standard-library test suite on Python 3.11, 3.12, and 3.13.
- The demo finds an intentional difference and produces valid JSON.
- Errors fail clearly instead of silently skipping invalid configuration.
- Performance claims include a reproducible workload and environment.

## 8. Roadmap

### v0.2 — Reproducers and report ergonomics
- Shell-escaped re-run commands.
- Bounded output-difference previews.
- Versioned report schema and replay of saved cases.
- Optional JUnit/SARIF export after the report contract stabilizes.

### v0.3 — Structured adapters
- Schema-driven JSON generation.
- An adapter interface for local HTTP and protocol domains.
- Explicit policy for environment variables and nondeterministic outputs.

### v0.4 — Isolation and observability
- Separately reviewed container-backed execution.
- Resource limits and bounded output capture.
- Optional filesystem-effect observation.

### v1.0 — Trustworthy compatibility workflows
- Stable API and report schema.
- Regression fixtures from minimized cases.
- Reproducible benchmark suite and methodology.
- Security review for any isolation backend.

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| False confidence after a clean run | State prominently that sampled tests do not prove equivalence. |
| Dangerous target commands | Shell-free invocation, timeouts, warnings, and future isolation. |
| Unbounded output or memory use | Document current limit; prioritize output caps before untrusted targets. |
| Slow minimization | Small default trial budget and configurable limits. |
| Unclear user value | Validate with maintainers of parsers, ports, and replacements. |
| Scope creep | Keep v0.x centered on CLI differential testing. |

## 10. Success measures

Prioritize usefulness over vanity metrics: percentage of findings reproduced from saved inputs; minimizer reduction rate; false-positive rate on repeat runs; time to first useful finding; confirmed compatibility bugs fixed; regression fixtures contributed; and onboarding success. Stars and downloads are reach signals, not product validation.

## 11. Release checklist

- Tests pass on supported Python versions.
- Installation and README demo work from a clean checkout.
- Commands and documented exit codes match actual behavior.
- Reports are valid JSON and contain enough evidence to reproduce findings.
- License, security boundaries, changelog, and known limitations are clear.
- No credentials, proprietary inputs, personal data, or generated caches are committed.
