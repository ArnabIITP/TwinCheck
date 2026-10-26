# Changelog

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
