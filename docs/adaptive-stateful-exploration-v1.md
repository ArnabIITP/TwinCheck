# Adaptive stateful exploration v1

TwinCheck provides two explicit exploration modes for resettable, local HTTP workflows. Static exploration remains the default to preserve existing schedules. Adaptive exploration is an opt-in alpha algorithm that can generate bounded paired mutations after seeing new response behavior.

## Run it

Install TwinCheck, then run against two trusted loopback services and a user-authored reset workflow:

\`\`\`bash
twincheck explore-http-sequence \\
  --reference-url http://127.0.0.1:8001 \\
  --candidate-url http://127.0.0.1:8002 \\
  --sequence examples/sequences/cart-create-add-read-v1.json \\
  --reset-sequence examples/sequences/cart-reset-v1.json \\
  --allow-side-effects \\
  --mode adaptive \\
  --seed 19 \\
  --cases 40 \\
  --max-adaptive-candidates 8 \\
  --max-run-seconds 300 \\
  --output adaptive-report.json
\`\`\`

Use \`--mode static\` to select the seeded, pre-generated mutation pool. Static mode remains the default. Both modes require the explicit \`--allow-side-effects\` acknowledgement because requests can change local state. A reset sequence is required; embed explicit read-only health assertions where the fixture supports them.

## Algorithm contract

Adaptive mode begins with the same seeded static candidate pool. After a candidate executes, TwinCheck computes value-free response-branch signatures, adjacent transition signatures and difference categories. A newly observed branch, transition or difference at a named step can trigger generation of paired scalar-boundary mutations for the nearest later workflow step with at least two literal scalar body fields. These combinations are candidates that are absent from the static generator's single-field mutation pool.

Candidate generation is bounded by \`--max-adaptive-candidates\`; candidate execution is bounded by \`--cases\`. \`--max-run-seconds\` prevents new candidate or minimization trials from starting after the deadline. An in-flight workflow can finish, but its total request time is bounded using the remaining budget, the per-request timeout and the maximum sequence size. Reset and health checks continue to run before each candidate and each minimization trial. Declared direct dependencies are still validated; the adaptive generator changes body values and does not reorder steps.

The report records the algorithm version, mode, seed, generated and executed counts, generation reasons, selection reasons, new response branches/transitions/difference signatures, minimization outcomes, the run budget and stop reason. The generation metadata does not copy body values or raw response values, and sensitive-looking field names are redacted from adaptive mutation pointers.

## Compare modes

Run the same fixed v0.9-derived synthetic case under the same seed and budgets:

\`\`\`bash
python benchmarks/compare_exploration_modes.py \\
  --case stateful-read-ordering \\
  --seed 19 \\
  --max-cases 12 \\
  --max-run-seconds 60 \\
  --minimization-trials 12 \\
  --output exploration-mode-comparison.json
\`\`\`

The comparison records candidate counts, executions, unique response branches, transitions and difference signatures, findings, minimization outcomes and elapsed time. These are measurements of the named synthetic fixture on the machine and Python version recorded in the output. They are not general performance or superiority claims.

## Limits

- Adaptive generation is a small deterministic heuristic, not automatic learning of an application's full state machine.
- It currently composes two scalar boundary changes in a later request body. It does not synthesize arbitrary new endpoints, protocol states, or mutation operators.
- Reproducibility is expected for the same algorithm version, seed, sequence, contract, budgets and deterministic target observations. Nondeterministic services can change the feedback and therefore the schedule.
- Response-shape and transition signatures are not instrumented source-code coverage, and novelty does not prove exhaustive testing.
- A reset-health contract verifies only the explicit assertions. It cannot prove external or unobserved state is clean.
- Loopback targeting is not a sandbox. Only test with trusted targets and synthetic data.
- Request sequences, original input values and findings can still contain sensitive application data; inspect evidence artifacts before sharing them.
