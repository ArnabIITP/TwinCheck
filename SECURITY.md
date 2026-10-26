# Security Policy

## Supported versions

Security fixes are expected for the latest release. This is an early prototype and does not yet have a formal support window.

## Reporting a vulnerability

Do not publish credentials, private data or exploit details in a public issue. Contact the repository maintainer privately through GitHub's security advisory feature if it is enabled; otherwise use a private contact channel listed on the maintainer's GitHub profile.

## Security boundaries

TwinCheck is a developer testing tool, **not a sandbox**. It launches the configured commands with the current user's permissions. Only run trusted programs and corpus inputs. The initial version does not enforce CPU/memory limits, does not isolate file-system or network access, and captures process output without a hard byte limit. Do not expose a service that runs user-supplied TwinCheck commands.

Command arguments are parsed and launched without a shell (`shell=False`), which avoids shell interpretation but does not make an arbitrary executable safe. A future sandbox should be designed and reviewed separately before TwinCheck is marketed for untrusted workloads.
