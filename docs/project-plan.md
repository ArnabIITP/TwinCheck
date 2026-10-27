# TwinCheck — Project Plan

**Status:** v0.6.0a1 alpha / local-first differential testing  
**Primary goal:** Make behavioral compatibility testing reproducible, practical, and evidence-based.  
**Initial audience:** Developers replacing libraries or tools, language-runtime implementers, maintainers of ports/forks, and teams migrating parsers or data processors.

## 1. Problem statement

A replacement implementation can pass its normal test suite while differing from the original on obscure inputs. Differences may include output formatting, error handling, exit codes, boundary values, Unicode, timeouts, or malformed inputs. A developer needs more than a yes/no result: they need an input that reproduces the difference and a stable artifact that can be added to a regression suite.

TwinCheck compares the observable behavior of a reference command and a candidate command against the same deterministic input cases. It records the evidence and can try to shrink a failing case.

## 2. Product principles

1. **Execute to verify.** A finding exists only when two actual executions produce a measured difference.
2. **Reproducible by default.** Every run records the seed, strategy, input hash, commands, and observations.
3. **Local-first and dependency-light.** The core has no runtime third-party dependencies and does not upload inputs.
4. **Safe defaults, honest boundaries.** Commands are launched without a shell, each run has a timeout, and documentation clearly says this is not a sandbox.
5. **Small reliable core before broad claims.** Command-line behavior comes before browser automation, protocol reconstruction, binary analysis, or claims of formal equivalence.
6. **AI is optional.** Future agents may suggest inputs or explain findings, but generated explanations never replace execution evidence.

## 3. Main user journeys

### Journey A — Validate a replacement

1. Choose a known-good reference command and a replacement command.
2. Run a seeded set of built-in edge cases and generated inputs.
3. Review a terminal summary and machine-readable JSON report.
4. Re-run an individual input manually.
5. Minimize the input and add it to the replacement's normal test suite.

### Journey B — Re-run a discovered bug

1. Put known UTF-8 regression inputs in a corpus directory.
2. Execute both implementations against the corpus.
3. Fail CI if any configured observable differs.
4. Keep the report as an artifact for review and debugging.

### Journey C — Extend a domain

1. Add a domain-specific input adapter or generator.
2. Define which outputs count as equivalent and which are meaningful differences.
3. Add fixed regression cases and tests for the adapter.
4. Document limitations and reproduce benchmark claims.

## 4. Scope

### v0.1 — Implemented foundation

- Python 3.11+ command-line package.
- Deterministic, seeded text, integer, JSON, and mixed input strategies.
- Optional UTF-8 corpus directory.
- Shell-free subprocess invocation, stdin or `{input}` argument mode, and per-process timeout.
- Comparisons for stdout, stderr, return code, and timeout status.
- Opt-in output normalization controls.
- Bounded delta-debugging minimizer.
- Terminal summary and JSON report.
- Unit tests, sample bug, CI workflow, security policy, contribution guide, and roadmap.

### v0.2 — Reproduction and reporting

- A clear re-run command for each finding, with correct quoting for the current platform.
- Bounded side-by-side stdout/stderr diff excerpts.
- JUnit XML export for standard test dashboards.
- Replay and promotion of minimized inputs into a regression corpus.
- Stronger validation for command and corpus configuration.
- A stable report schema with backward-compatibility tests.

### v0.3 — Structured inputs and local HTTP (implemented alpha)

- JSON Schema-driven generation with deterministic seeds for a documented schema subset.
- Local HTTP adapter for comparing generated JSON requests against two loopback services.
- Versioned compatibility contracts and explicit request/response observation policy.

### v0.4 — Stateful HTTP workflows (implemented alpha)

- Multi-request sequences with response captures, independent cookie jars, and replayable step-level evidence.
- Optional reset-before-repeat sequence, requiring successful 2xx responses from both targets.

### v0.5 — Transition-aware workflows (implemented alpha)

- Deterministic mutations of JSON body values, adjacent step order, step removal and step repetition.
- A user-authored state-reset workflow run before each generated candidate and minimization trial.
- Bounded step-level delta debugging that preserves a selected mismatch at the same named step.
- Reset-backed reports that can be replayed against explicitly supplied loopback targets.

### v0.6 — Feedback-guided exploration (implemented alpha)

- [x] Fingerprint response branches by HTTP status, content type and value-free JSON shape.
- [x] Fingerprint adjacent response transitions and mismatch categories.
- [x] Prioritize the bounded seeded mutation pool using response novelty, new mutation features and category balance.
- [x] Record queue scores/reasons and per-case coverage novelty in the report.
- [x] Minimize request bodies after step deletion, using a shared reset-backed trial budget.

Known limits: response-shape fingerprints are not source-code instrumentation; mutation candidates are generated up front and ranked from feedback; reset correctness is still a property of the user's service reset implementation.

### Next — Stronger workflow semantics

- Service-specific reset markers or state fingerprints, not just HTTP 2xx checks.
- Explicit precondition/dependency hints and safer operation ordering.
- Dynamically generated mutations from newly observed response behavior, beyond ranking a pre-generated pool.
- More representative compatibility benchmarks with repeatable, externally reviewable fixtures.

### Later — Instrumentation, observation and isolation

- Filesystem observation for explicitly configured temporary directories.
- A container-isolation backend for supported environments.
- Resource limits for memory, process counts, output size, and runtime where the platform supports them.
- Better handling of nondeterminism, flaky observations, and repeated trials.

### v1.0 — Reliable compatibility workflow

- Stable public Python API and report schema.
- Documented platform support and reproducibility contract.
- Regression fixture export and CI integrations.
- Performance evaluation with reproducible datasets and published methodology.
- Security review for isolation and process management.
- Clear support policy and migration notes.

## 5. Non-goals for v0.x

- Proving arbitrary programs equivalent from sampled inputs.
- Executing untrusted programs safely without an isolation backend.
- Reconstructing an application's internals or decompiling binaries.
- Requiring an LLM, cloud account, telemetry, or network access at runtime.
- Pretending all outputs should be byte-for-byte identical; domain adapters must define their equivalence rules.

## 6. Technical architecture

- `generators.py`: deterministic strategies and corpus loading.
- `runner.py`: parsed argv, process invocation, stdin/argument input, timeout, raw observations.
- `compare.py`: output normalization, discrepancy categories, and minimization.
- `engine.py`: orchestration, per-case findings, aggregate summary and limitations.
- `report.py`: stable JSON serialization and terminal summary.
- `cli.py`: argument parsing, exit codes, and output destinations.

The dependency direction is inward: the CLI calls the engine; the engine combines generators, runner, comparison logic, and reporting. Core execution uses only the Python standard library.

### Proposed finding contract

Each finding should preserve:

- stable case index and SHA-256 of the exact UTF-8 input;
- exact input text (with JSON escaping when serialized);
- difference categories;
- reference and candidate return codes, stdout, stderr, timeout status, and durations;
- whether minimization was attempted, trial count, and whether the budget was exhausted.

Do not compare durations by default: scheduler noise would create excessive false positives. A future performance mode should be a separate feature with warm-up, repetition, statistics, and explicit thresholds.

## 7. Safety and privacy model

The program runs locally and makes no network requests as part of its core operation. However, target commands inherit the current user's permissions and may access local files or networks. `shell=False` reduces shell interpretation; it does not make a target safe.

Before a safe-by-default untrusted-target mode can be advertised, the project needs a supported isolation backend, resource limits, output caps, process-tree cleanup, and adversarial tests. Until then:

- execute only commands you trust;
- do not use production secrets or sensitive corpora;
- consider a disposable VM/container for unfamiliar targets;
- treat reports as potentially sensitive because they store exact inputs and outputs;
- review changes to process execution and report serialization as security-sensitive.

## 8. Testing strategy

- Unit tests for deterministic generation, output normalization, difference categories, timeouts, command parsing, and minimizer behavior.
- Integration tests using tiny known reference/candidate programs.
- Regression tests for every confirmed bug in the engine.
- CLI tests for exit codes and valid JSON reports.
- CI matrix for supported Python versions.
- Future adapter contract tests, platform-specific process tests, and property tests for input and report invariants.

Every performance claim should include environment, workload size, command lines, trial count, and a reproducible script. Do not use a demo output as a benchmark claim.

## 9. Release gates

A version may ship only when:

- all tests pass on supported Python versions;
- README examples work from a fresh checkout;
- help text and exit codes match the documentation;
- reports can be parsed as valid JSON and include schema/version fields;
- known limitations and security implications are visible;
- the changelog identifies user-visible changes;
- no credentials, proprietary inputs, personal data, or generated cache files are included.

## 10. Success metrics

Track usefulness rather than vanity metrics alone:

- percentage of findings that can be reproduced with the saved input;
- minimizer success rate and median reduction in input size;
- false-positive rate for repeated runs;
- time to first useful finding on a published benchmark corpus;
- number of confirmed user-reported bugs fixed;
- adapter adoption and regression fixtures contributed by users;
- onboarding success: how quickly a new user can compare two toy programs from a clean checkout.

GitHub stars and downloads are useful reach signals but do not substitute for these measures.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| False confidence after a clean run | State prominently that sampled tests do not prove equivalence. |
| Dangerous target commands | Shell-free invocation, timeout, warnings, and future isolation backend. |
| Unbounded output or memory use | Document current limit; add bounded output capture before untrusted-target support. |
| Nondeterministic targets | Repeat mode and explicit flakiness handling in a later version. |
| Slow minimization | Default to a small trial budget, make limits explicit, report trials. |
| Hard-to-compare structured output | Make equivalence policies explicit and domain-specific. |
| Scope creep | Keep v0.x centered on CLI differential testing until release gates are met. |

## 12. Immediate next actions

1. Publish v0.1 to a private repository and keep the initial commit small and reviewable.
2. Ask 3–5 developers who maintain parsers, ports, or replacement tools to try the demo.
3. Collect representative compatibility failures and add them as tests only when redistribution is permitted.
4. Prioritize v0.2 based on repeated user pain, not the most impressive-sounding feature.
5. Make a public release after install instructions, CI, license, and security notes are verified.

## v0.7 — portable stateful regression workflow

A stateful finding should become a checked-in regression artifact instead of remaining embedded in a verbose run report. The export format includes one sequence, the optional pinned reset sequence, the compatibility contract, source provenance, and file/canonical hashes. It intentionally omits response traces and request-header values. Replay is limited to explicitly provided loopback URLs and requires an explicit acknowledgement that requests may change local data. The pack loader fails closed on hash mismatches, unknown manifest fields, unexpected paths, symlink files, and modified sequence/contract definitions.

The milestone is implementation-complete locally; promotion requires the complete suite to pass in CI on Python 3.11, 3.12, and 3.13.
