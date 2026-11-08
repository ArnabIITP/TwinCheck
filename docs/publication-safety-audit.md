# Publication Safety Audit

**Status: NOT CLEARED FOR PUBLICATION**

Audit date: 2026-11-08  
Repository: `ArnabIITP/TwinCheck`  
Default branch at audit time: `main`

This is a working audit record, not a security certification. Do not change repository visibility based on this document alone.

## Repository state

- Repository visibility was confirmed as **private** during this audit.
- The main branch was at commit `9e5b849c0e8861b2e5b31b89f76f17ee7f586dbb`.
- The mainline commit search returned 33 commits.
- An open inventory benchmark PR (#15) contains 11 changed files and has a separate branch history.
- A dedicated `work` branch was created from current `main` for release-safety changes.

## Manual history triage

A pattern-based review was performed against the GitHub-provided patches for all 33 commits returned by the repository commit search, plus the 11-file patch for PR #15. The patterns covered common private-key headers, AWS access-key IDs, GitHub token formats, Slack token formats, credential-bearing URLs, and likely secret assignments.

- No likely secret pattern was identified in the reviewed mainline patches.
- One credential-URL pattern match was an intentional localhost test fixture that verifies rejection of embedded URL credentials. It is test data, not a usable credential.
- No matches were identified in the PR #15 patch.

**Limitations:** This manual pattern review is not equivalent to Gitleaks, does not prove that no secret exists, and does not replace a full Git object/ref scan. The automated full-history Gitleaks workflow has been added but its successful execution and findings have not yet been verified. A human review of any scanner findings is still required.

## Controls added on the working branch

- Updated `SECURITY.md` to accurately describe the current alpha's process execution, bounded output capture, loopback HTTP restrictions, and sensitive evidence handling.
- Added a Gitleaks CLI workflow that checks out complete history and scans all refs and tags.
- Added CodeQL with the security-extended query suite. It is gated to run after the repository is public, when GitHub code-scanning upload is available.
- Added OpenSSF Scorecard with SARIF reporting, also gated to the public-repository phase.
- Added weekly Dependabot updates for Python dependencies and GitHub Actions.

These changes are proposed in PR #18 and are not yet merged into `main`.

## Remaining publication blockers

- [ ] Execute the full-history/all-ref Gitleaks workflow and review every finding.
- [ ] Investigate any real credential exposure and rotate/revoke affected credentials. Removing a value from a later commit is not sufficient.
- [ ] Confirm GitHub Actions runs successfully for the security workflow.
- [ ] Review the complete current repository tree, including examples, fixtures, reports, documentation, and release artifacts.
- [ ] Review all refs and tags, including branches not represented by the default-branch commit list.
- [ ] Confirm private vulnerability reporting is enabled or provide a reliable private reporting route.
- [ ] Review repository metadata, license, third-party notices, and release artifacts.
- [ ] Only then make a final publication decision.

## Decision

**Do not make the repository public yet.** The manual triage did not identify a likely real secret in the reviewed patches, but the authoritative automated all-ref scan has not been executed and reviewed. The public launch gate remains closed until the blockers above are resolved.
