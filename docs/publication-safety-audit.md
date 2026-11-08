# Publication Safety Audit

**Status: NOT CLEARED FOR FIRST PYPI PUBLICATION**

Audit date: 2026-11-08  
Repository: `ArnabIITP/TwinCheck`  
Default branch: `main`  
Reviewed mainline commit: `bbc91b2cf7ee57a57fd01165b2978d64bd014c68`

This is a working release audit, not a security certification. The GitHub repository is already public. This audit controls the first package publication, not repository visibility.

## Repository and refs

- Repository visibility is **public** and `main` is the default branch.
- PR #18 established the public-alpha release infrastructure.
- Dependabot PRs #19–#23 were reviewed and merged.
- PR #24 (immutable GitHub Actions pins and publication documentation corrections) was merged as `bbc91b2cf7ee57a57fd01165b2978d64bd014c68`.
- There are no open pull requests.
- The former inventory benchmark PR #15 is closed without merging; its branch is not present.
- The active project branches are `main` and `work`. Two stale Dependabot branches remain for already-merged PRs #21 and #23; they are not open changes.
- No release tags or GitHub Releases existed at audit time.

## Secret scanning and security analysis

**Gitleaks:** The full-history/all-ref scan passed on the reviewed mainline commit in run [42472873797](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472873797). No findings were reported.

**CodeQL:** The CodeQL security-extended analysis completed successfully in run [42472873797](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472873797), and SARIF results were uploaded. A successful scan does not mean there are no alerts. Review the repository's Code Scanning alerts page and triage any actionable findings before release. The connected GitHub access does not expose the alerts list.

**OpenSSF Scorecard:** Scorecard completed successfully in run [42472873797](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472873797), with an overall score of **5.6**. The latest report confirms:
- All 17 GitHub-owned GitHub Actions and all 3 third-party GitHub Actions are pinned to immutable commit SHAs.
- Pinned-Dependencies scored 3/10 because the build-tool `pip install` commands are not hash-pinned.
- Branch-Protection scored 0 and Code-Review scored 0 because `main` has no branch protection/ruleset requiring reviewed PRs and status checks.
- Fuzzing scored 0 because no fuzzing integration is configured.
- Packaging and Signed-Releases are not yet detected because no release has been published.
- Token-Permissions scored 10/10 and Dangerous-Workflow scored 10/10.

The action-SHA pinning finding from the earlier scan has therefore been addressed. Branch protection is a high-severity remaining hardening gap and should be configured before the first package release. Scorecard is a diagnostic signal, not a certification.

## Release artifact verification

The mainline CI run [42472884384](https://github.com/ArnabIITP/TwinCheck/actions/runs/42472884384) completed successfully on commit `bbc91b2cf7ee57a57fd01165b2978d64bd014c68`, including Linux/Python 3.11, 3.12 and 3.13 and Windows/Python 3.11. The CI distribution verifier passed in every matrix job.

The release-candidate artifact from that exact mainline commit was downloaded and independently inspected:

- Wheel: `twincheck-0.12.0a1-py3-none-any.whl`
- Source archive: `twincheck-0.12.0a1.tar.gz`
- GitHub Actions artifact SHA-256: `b538b1a9ef0681a5439c7f7d6d7a6aadf7d18233764c022ceb07329aff2e2950`
- Wheel SHA-256: `7a59eb1d5b78d1ce0f5ab246076e0904d3e9e15512b46157545801b63db4639b`
- Source archive SHA-256: `63e4e69dee7f2f097a2a764934ba38337121c3954fd631eaaf99a40a7e668b5e`
- Wheel metadata reports package `twincheck`, version `0.12.0a1`, Python `>=3.11`, and MIT license expression.
- The source archive contains 126 entries and all 34 files required by `scripts/verify_distribution.py`.
- The wheel installed successfully in a clean virtual environment outside the source checkout.
- The installed CLI reported `TwinCheck 0.12.0a1`; the expected stateful CLI options were present.
- The installed public Python API v1 smoke test passed.

These are verified artifacts from the reviewed mainline commit. They are not yet the final release-tag artifacts. The tag workflow must rebuild and verify the exact tagged source before a GitHub Release is published.

## Package and Trusted Publishing configuration

- Package metadata in `pyproject.toml` and `src/twincheck/__init__.py` agrees on name `twincheck` and version `0.12.0a1`.
- The publishing workflow uses GitHub environment `pypi`, grants only `contents: read` and `id-token: write` to the publishing job, and uses OIDC rather than a long-lived PyPI token.
- The maintainer reports that a PyPI pending publisher and GitHub `pypi` environment have been created. The required PyPI pending-publisher values are owner `ArnabIITP`, repository `TwinCheck`, workflow filename `publish.yml`, and environment `pypi`.
- The repository workflow path is `.github/workflows/publish.yml`; PyPI's workflow filename field must be `publish.yml`, not the full path.
- The PyPI account-side pending-publisher configuration cannot be read through connected GitHub repository access. It remains to be confirmed in PyPI settings or by a successful first publish.
- A pending publisher does not reserve the project name. Confirm that `twincheck` is still available immediately before publishing.
- No PyPI release has been published at the time of this audit.

## Remaining release blockers

- [x] Verify repository is public and `main` is the default branch.
- [x] Review current branch and pull-request state; confirm PR #15 is closed unmerged and PRs #19–#24 are merged.
- [x] Confirm no release tags or GitHub Releases currently exist.
- [x] Run full-history/all-ref Gitleaks on the public mainline: no findings.
- [x] Run CodeQL and upload security-extended analysis results.
- [x] Run OpenSSF Scorecard and record its current findings.
- [x] Pin all GitHub Actions dependencies to immutable commit SHAs.
- [x] Verify wheel and source archive from the final mainline CI, including metadata, required source files, clean installation, CLI and Python API v1 smoke tests.
- [ ] Configure branch protection/ruleset for `main`: require pull requests, at least one independent approval, required CI/security status checks, up-to-date branches, and prevent force pushes/deletion or unrestricted bypass.
- [ ] Review Code Scanning alerts and triage any actionable CodeQL findings.
- [ ] Enable or confirm GitHub private vulnerability reporting under Settings → Security & quality → Advanced Security. The connected GitHub read operation did not expose this setting, so it is not marked verified.
- [ ] Confirm the PyPI pending publisher values in the PyPI account: owner `ArnabIITP`, repository `TwinCheck`, workflow filename `publish.yml`, environment `pypi`.
- [ ] Confirm the `twincheck` project name is still available immediately before the first upload.
- [ ] Create tag `v0.12.0a1` on the reviewed commit; inspect the generated draft GitHub Release and its rebuilt wheel/source artifacts.
- [ ] Publish the GitHub Release only after all preceding checks are complete, then verify the PyPI project page and install the exact published version in a clean environment.

## Decision

**Do not publish to PyPI yet.** The final mainline build, artifact inspection, Gitleaks, CodeQL and Scorecard workflows have succeeded. Immutable action pinning is complete. The remaining blockers are branch protection, human review of CodeQL alerts, confirmation of GitHub private vulnerability reporting, verification of the PyPI account-side publisher and project-name availability, and final tag/draft-release inspection.
