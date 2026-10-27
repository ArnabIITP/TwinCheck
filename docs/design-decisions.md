# Design Decisions

This document records the current decisions that shape TwinCheck. They can be revisited as the project grows, but changes should be deliberate and tested.

## DD-001: Evidence must come from real execution

**Decision:** A behavioral finding is emitted only after running the reference and candidate against an input and observing the configured comparison result.

**Why:** AI summaries and static guesses are useful for exploration but are not evidence that two implementations differ. Future agent integrations may propose cases or explain reports, but the engine validates them through execution.

## DD-002: Start with command-line behavior

**Decision:** v0.x targets CLI programs with UTF-8 text inputs and observations of stdout, stderr, exit code, and timeout state.

**Why:** The interface is language-agnostic, easy to demonstrate and test, and a useful common denominator. Broad claims about protocols, binaries and GUI applications would be misleading before adapters exist.

## DD-003: Keep the core local and dependency-light

**Decision:** The runtime uses the Python standard library and does not require an LLM API, cloud account, or remote service.

**Why:** Local runs keep test inputs under the user's control and allow TwinCheck to be used in offline, research and CI environments. Optional integrations must not be mandatory for core correctness.

## DD-004: Commands are launched without a shell

**Decision:** The command string is tokenized into argv and launched with `shell=False`.

**Why:** This avoids shell interpretation of metacharacters. It does not make the executable safe; target commands are still fully privileged unless run in a separate isolation backend.

## DD-005: Explicit bounds before broad target support

**Decision:** Use a per-process timeout, output retention cap, and bounded minimization budget.

**Why:** Differential testing can multiply execution cost. Bounded defaults make a first run easier to reason about. Output cap enforcement is polling-based and therefore approximate; a stronger quota mechanism belongs in a future hardened backend.

## DD-006: Report instability separately

**Decision:** Optional repeated runs classify within-target observable variation as `reference_unstable` or `candidate_unstable`.

**Why:** A random or environment-sensitive target should not be silently treated as deterministic. Repeated observations are a signal for investigation, not a proof of statistical stability.

## DD-007: Replay commands are explicit

**Decision:** The replay command loads an input from a report but requires the user to supply commands again.

**Why:** A report can come from an untrusted source. Automatically executing its embedded command strings would turn report inspection into command execution.

## DD-008: No universal equivalence claims

**Decision:** A successful run means no difference was observed among the tested cases under the selected observation and normalization policy.

**Why:** General program equivalence is far beyond sampled input testing. User-facing language should remain precise and evidence-bounded.

## DD-009: Avoid claiming performance without a protocol

**Decision:** The repository includes a reproducible smoke benchmark format, but README badges do not claim speedups or universal rankings.

**Why:** Throughput depends on target startup cost, operating system, command behavior and workload. Any future benchmark claim needs exact inputs, commands, runtime versions, rounds and hardware.


## DD-010: Compatibility rules are explicit and fingerprinted

**Decision:** A versioned JSON contract declares exact or JSON-semantic comparison per output stream, JSON Pointer paths to ignore, and whether exit codes/timeouts are part of the compatibility promise. Each report stores the normalized contract and a SHA-256 fingerprint.

**Why:** Byte-for-byte comparison is often too strict for structured response bodies, but implicit normalization can hide real regressions. Teams must review which fields they are choosing to ignore. Fingerprinting the policy makes results auditable and lets future regression tooling bind a fixture to the contract that found it.


## DD-011: Findings should become portable regression inputs

**Decision:** `export-pack` creates a new directory containing deduplicated exact UTF-8 counterexamples, a versioned manifest and the compatibility contract. `replay-pack` verifies the manifest, all input hashes and the contract fingerprint before executing explicitly supplied commands.

**Why:** Discovery is only one part of compatibility work. Teams need a durable path from a mismatch to a regression check that can live in a repository and run after refactors. The contract hash ensures the case isn't quietly replayed under different semantics. Pack inputs are data and are never interpreted as commands.


## DD-012: Schema generation fails closed outside a documented subset

**Decision:** JSON Schema-driven input generation uses a dependency-free subset and rejects unsupported validation keywords. Reports record the exact schema-file SHA-256, sample count and seed.

**Why:** Silently ignoring a constraint can produce invalid test cases while giving the user false confidence. Full JSON Schema semantics are broader than a small standard-library generator can reliably implement; unsupported features need explicit errors and a path back to a known corpus.

## DD-013: The first HTTP adapter only targets loopback services

**Decision:** `compare-http` accepts only `localhost`, `127.0.0.1` and `::1` origins, uses one fixed request path with JSON body samples, compares status/body plus an explicit response-header allowlist, and omits request-header values from reports.

**Why:** The first adapter is for a developer's local reference/candidate services, not a generic scanner or remote API client. Keeping the scope local reduces accidental network exposure and credential leakage, but does not sandbox the local services or CLI target programs.


## DD-014: Stateful workflows are explicit and replayable

**Decision:** Represent stateful API tests as a bounded JSON sequence with named steps and JSON Pointer captures. Keep each side's cookie jar and variable store separate. Store the source and canonical sequence hash with step-level response evidence; replay only after the user supplies local target origins and explicitly acknowledges side effects.

**Rationale:** An API compatibility break can emerge only after resource creation or session establishment. This adds workflow-level evidence without claiming to synthesize valid state machines or discover arbitrary transition graphs. Explicit sequences are deterministic and reviewable.

**Trade-off:** Users must author representative workflows and decide which volatile values belong outside the contract. Captured IDs and session cookies are not shared between implementations, so each follows its own state. Trace evidence can contain sensitive request or response data; test fixtures should be synthetic.


## DD-015: Automatic workflow exploration requires a user-authored reset

**Decision:** `explore-http-sequence` requires a reset sequence and explicit `--allow-side-effects`. Before every variant and every minimization trial, TwinCheck runs the reset against both loopback targets and aborts if any step times out, has a transport error, fails capture/rendering, or returns a non-2xx response. Variants include body-value boundary substitutions, adjacent swaps without direct capture dependencies, step removal, and step repetition.

**Why:** Stateful exploration multiplies side effects and can otherwise confuse observations from earlier variants with later ones. A repeatable reset is a minimum condition for useful comparisons; however, a 2xx response is only a declared success signal and cannot prove all hidden state was cleared.

**Trade-off:** Users must implement a trustworthy test reset endpoint. The first release explores a bounded mutation strategy and does not infer arbitrary state machines or guarantee globally minimal workflows.


## DD-016: Use response-behavior feedback to prioritize bounded exploration

**Decision:** The explorer runs the baseline first, fingerprints per-operation response branches from HTTP status, content type and JSON body shape, fingerprints adjacent response transitions, then ranks a seeded pre-generated candidate pool using new mutation features, category balance and steps that recently exposed new behavior. Reports record the score, reasons and newly observed signatures. Actual response values are not included in coverage fingerprints.

**Why:** Uniformly shuffling a fixed mutation list does not use what earlier executions taught us. Response-shape feedback gives a low-instrumentation signal that works with black-box local APIs while keeping runs reproducible and avoiding source-code coupling.

**Trade-off:** These are response-behavior signatures, not source-code branch coverage. The scheduler prioritizes a bounded candidate pool; it does not dynamically synthesize arbitrary new mutations from observations. Repeated operation names are normalized for feedback so duplicating a step alone does not masquerade as a new response branch.


## DD-017: Minimize the reproducer after minimizing the workflow

**Decision:** First remove whole steps with the existing bounded delta-debugger, then try deleting JSON object fields/array items and simplifying scalar body values. A shrink is accepted only if the selected mismatch category still occurs at the same named step after a successful reset; all trials share the configured budget.

**Why:** A three-step test with a 20-field body is still an expensive and noisy regression fixture. Smaller request bodies can reveal the essential condition and make future compatibility checks easier to review.

**Trade-off:** Shrinking is greedy and budgeted, not globally optimal. Type changes and invalid requests may fail to preserve the target mismatch, in which case they are discarded. Replay evidence continues to store the complete minimized request body, so users should keep test data synthetic.
