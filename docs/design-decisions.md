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
