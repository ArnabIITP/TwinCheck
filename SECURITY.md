# Security Policy

## Project status

TwinCheck is pre-1.0 alpha software. Security fixes are prioritized for the latest alpha release. No long-term support window is currently promised.

## Reporting a vulnerability

Please do not publish credentials, private data, or exploit details in a public issue. Use GitHub's private vulnerability reporting / security advisory feature for this repository when available. If private reporting is unavailable, contact the maintainer through the private contact channel on the maintainer's GitHub profile. Please include the affected version or commit, impact, and a minimal reproduction that does not expose real secrets or customer data.

## Security boundaries

TwinCheck is a developer testing tool, **not a sandbox**. It launches configured target commands with the current user's permissions. Only run programs and workflows you trust and are authorized to test. TwinCheck does not isolate filesystem or network access, enforce CPU or memory quotas, or make untrusted executables safe.

The CLI retains bounded stdout/stderr output and reports truncation, but this is not a substitute for disk quotas or OS-level resource isolation. A target can still perform arbitrary actions available to the user, write files, access the network, spawn processes, or consume resources outside TwinCheck's controls.

The HTTP adapters are intended for local test services and restrict requested target origins to loopback addresses. This does not sandbox the service itself or prevent it from making outbound connections. Do not expose a service that accepts arbitrary user-supplied TwinCheck commands, workflows, or corpora.

## Sensitive evidence

JSON reports and replay artifacts can contain exact failing inputs and captured program or service output. Treat them as potentially sensitive. Do not commit or publish reports derived from production systems, customer data, credentials, or proprietary inputs without reviewing and sanitizing them. Request header values are intentionally excluded from HTTP evidence, but a service can echo sensitive values in its response.

## Supported security controls

The project uses GitHub Actions CI and is introducing automated secret, source-code, dependency, and repository-posture checks. These checks reduce risk but do not constitute a security certification or guarantee that every vulnerability or secret will be detected.
