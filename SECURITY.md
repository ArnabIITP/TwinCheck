# Security Policy

## Supported versions

Security fixes are expected for the latest release. TwinCheck is an early prototype and does not yet have a formal support window.

## Reporting a vulnerability

Please do not publish credentials, private data, or exploit details in a public issue. Contact the repository maintainer privately through GitHub. If GitHub Security Advisories are enabled for this repository, use the private vulnerability reporting feature.

## Security boundaries

TwinCheck is a developer testing tool, **not a sandbox**. It launches configured commands with the current user's permissions. Only run trusted programs and input corpora. The current version does not isolate the filesystem or network, enforce CPU or memory limits, or hard-cap subprocess output. Do not expose a service that runs user-supplied commands.
