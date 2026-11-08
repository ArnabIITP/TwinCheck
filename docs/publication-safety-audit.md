# Publication Safety Audit

**Status: NOT CLEARED FOR FIRST PYPI PUBLICATION**

Audit date: 2026-11-08  
Repository: `ArnabIITP/TwinCheck`  
Default branch: `main`  
Reviewed mainline commit: `b19ea73211a388efc333e29daff03d7a4d0cb2af`

This is a working release audit, not a security certification. The GitHub repository is already public. This audit controls the first package publication, not repository visibility.

## Repository and refs

- Repository visibility was verified as **public**.
- Default branch is `main`.
- The release-readiness work was merged by PR #18.
- Dependabot PRs #19–#23 were reviewed and merged; there are currently no open pull requests.
- Two Dependabot branches remain visible for already-merged PRs #21 and #23. They are stale bot branches, not open changes.
- The former inventory benchmark PR #15 is closed without merging; its branch is not present in the current branch list.
- Current refs include `main`, `work`, and the two stale Dependabot branches noted above.
- The GitHub tags endpoint returned no tags at audit time. No release tag has been created.

## Secret scanning and security analysis

**Gitleaks:** The full-history/all-ref scan passed on mainline commit `b19ea73211a388efc333e29daff03d7a4d0cb2af` in run [42472188223](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472188223). The log reports 61 commits scanned, approximately 785,496 bytes scanned, and no leaks found.

**CodeQL:** The CodeQL security-extended analysis completed successfully in run [42472188223](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472188223). It scanned 44 of 44 Python files and uploaded SARIF results successfully. A successful scan does not mean there are no alerts; review the repository's Code Scanning alerts page before release.

**OpenSSF Scorecard:** Scorecard completed and uploaded results in run [42472188223](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472188223). It identified improvement areas including action dependencies not pinned to immutable SHAs, no branch protection on `main`, no fuzzing integration, and no published release yet. The action-pinning issue is being addressed on `work`; branch protection and fuzzing remain follow-up hardening items. Do not present the Scorecard result as a certification.

**Manual history triage:** The earlier manual review covered the mainline commit patches and the closed inventory PR patch. One credential-URL match was an intentional localhost fixture used to test rejection of embedded URL credentials. No usable credential was identified in that review. Gitleaks now provides a newer full-history check on the public repository.

## Release artifact verification

The mainline CI run [42472188064](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472188064) completed successfully on commit `b19ea73211a388efc333e29daff03d7a4d0cb2af`, including the Linux/Python 3.11, 3.12 and 3.13 jobs and Windows/Python 3.11.

The verified release-candidate artifact was downloaded from that run and independently inspected:

- Wheel: `twincheck-0.12.0a1-py3-none-any.whl`
- Source archive: `twincheck-0.12.0a1.tar.gz`
- Wheel SHA-256: `2aac7a9fb1633281c7a7c18294bdc317c69bc2d81e673a71c3fabeb0efa624f2`
- Source archive SHA-256: `c88512cee12d879521382d15b65c3ece917746f9efc58cf1a85ec28db2b958ec`
- Wheel metadata reports package `twincheck`, version `0.12.0a1`, Python `>=3.11`, and MIT license expression.
- The source archive contains all 34 files required by `scripts/verify_distribution.py`.
- The wheel installed successfully in a clean virtual environment outside the source checkout.
- The installed CLI reported `TwinCheck 0.12.0a1`; the expected stateful CLI options were present.
- The installed public Python API v1 smoke test passed.
- The CI distribution verifier, including Twine metadata checks and isolated installation, passed.

These are verified artifacts from the reviewed mainline commit. They are not yet the final release-tag artifacts. The tag workflow must rebuild and verify the exact tagged source before a GitHub Release is published.

## Package and Trusted Publishing configuration

- Package metadata in `pyproject.toml` and `src/twincheck/__init__.py` agrees on name `twincheck` and version `0.12.0a1`.
- The publishing workflow uses GitHub environment `pypi`, grants only `contents: read` and `id-token: write` to the publishing job, and uses OIDC rather than a long-lived PyPI token.
- The maintainer reports that a PyPI pending publisher and GitHub `pypi` environment have been created. The repository workflow is `.github/workflows/publish.yml`; PyPI's workflow filename field must be exactly `publish.yml`, with owner `ArnabIITP`, repository `TwinCheck`, and environment `pypi`.
- The PyPI account-side pending-publisher configuration cannot be read through the connected GitHub repository access. It remains to be confirmed in PyPI settings or by a successful first publish.
- A pending publisher does not reserve the project name. Confirm that `twincheck` is still available immediately before publishing.
- No PyPI release has been published at the time of this audit.

## Remaining release blockers

- [x] Verify repository is public and `main` is the default branch.
- [x] Review current branch and pull-request state; confirm PR #15 is closed unmerged and PRs #19–#23 are merged.
- [x] Confirm no release tags currently exist.
- [x] Run full-history/all-ref Gitleaks on the public mainline: 61 commits, no findings.
- [x] Run CodeQL and upload results for 44 Python files.
- [x] Run OpenSSF Scorecard and record its improvement findings.
- [x] Verify wheel and source archive from CI, including metadata, required source files, clean installation, CLI and Python API v1 smoke tests.
- [ ] Merge the current immutable-action pinning updates from `work` after CI, Gitleaks, CodeQL and Scorecard pass on the updated commit.
- [ ] Review Code Scanning alerts and triage any actionable CodeQL findings.
- [ ] Enable or confirm GitHub private vulnerability reporting under Settings → Security & quality → Advanced Security. The connected GitHub read operation did not expose this setting, so it is not marked verified.
- [ ] Confirm the PyPI pending publisher values in the PyPI account: owner `ArnabIITP`, repository `TwinCheck`, workflow filename `publish.yml`, environment `pypi`.
- [ ] Confirm the `twincheck` project name is still available immediately before the first upload.
- [ ] Create the release tag only after the reviewed commit and version are final; inspect the generated draft release and its rebuilt artifacts.
- [ ] Publish the GitHub Release only after all preceding checks are complete, then verify the PyPI project page and install the exact published version in a clean environment.

## Decision

**Do not publish to PyPI yet.** The current release candidate is technically verified, and public-repository security scans have run. However, action pinning is being completed, CodeQL alerts need human review, and the PyPI account-side publisher configuration, package-name availability, and private vulnerability reporting setting still need confirmation. The first release remains gated on these items.
