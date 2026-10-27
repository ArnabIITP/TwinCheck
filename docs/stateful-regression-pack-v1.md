# Stateful HTTP regression pack v1

A stateful HTTP regression pack is a directory created by `twincheck export-http-sequence-pack` from a finding in a `stateful-http-sequence` or `stateful-http-exploration` report.

## Files

- `manifest.json`: format and provenance, source finding, source/canonical sequence hashes, reset state, and SHA-256 fingerprints.
- `sequence.json`: the selected finding's request workflow in normalized JSON.
- `reset-sequence.json`: present only when the source report pinned a reset workflow.
- `contract.json`: normalized compatibility rules used to compare the targets.

The pack intentionally excludes response observations and request-header values. Authentication headers must be supplied at replay time. Avoid secrets in the sequence/contract and prefer synthetic local fixtures.

## Integrity

The loader checks the manifest version and type, file hashes and canonical JSON hashes, strict sequence validation, the embedded contract fingerprint, reset metadata consistency, and known manifest fields. It refuses symbolic-link pack files and never overwrites an existing export destination.

The source sequence hash identifies the workflow file from the original report. The stored-file hash is separate because the pack serializes normalized JSON; replay records the hash of the exact packaged definition.

## Replay

`replay-http-sequence-pack` requires explicit reference/candidate loopback origins and `--allow-side-effects`. A pinned reset workflow runs before every repeat, and any reset-step failure aborts the tested workflow. An HTTP success code cannot prove that all hidden application state has been cleared.

Pack integrity does not make target services safe or requests side-effect free. Use disposable local services and sanitized data.

The manifest structure is documented by [`stateful-regression-pack-v1.schema.json`](stateful-regression-pack-v1.schema.json).
