# Threat Model and Safety Boundaries

## Intended deployment

TwinCheck is a developer tool run locally by someone who trusts both target programs. It is intended for compatibility testing of programs the user owns, maintains, or is authorized to examine.

## Assets to protect

- The host operating system, files, processes and network.
- Credentials or customer data contained in inputs or outputs.
- Reproducibility and integrity of the evidence report.
- The user's time and compute budget when targets hang or emit excessive output.

## Threats and current mitigations

| Threat | Current mitigation | Remaining gap |
| --- | --- | --- |
| Shell metacharacters execute through a shell | Commands are tokenized and launched with `shell=False` | The chosen executable can still perform arbitrary actions |
| Target hangs indefinitely | A per-process deadline; POSIX process-group termination is attempted | Platform-specific child process handling is not fully guaranteed |
| Target emits huge stdout/stderr | File-backed output plus a retained-byte cap and polling-based termination | A process can write extra bytes between polls; disk quotas are not enforced |
| Output contains invalid UTF-8 | Decode with replacement and record byte counts/truncation | This is not byte-exact binary comparison |
| Report contains a malicious command | Replay requires explicit reference/candidate commands from the user | A user can still voluntarily run an unsafe command |
| Report leaks sensitive input | JUnit failure text uses hashes/categories rather than raw input | JSON evidence intentionally contains exact failing input; users must secure artifacts |
| CLI target modifies host or reaches the network | Documentation warns that target commands run with current privileges | No filesystem, network, user, container, or syscall isolation |
| HTTP adapter used against a remote service | Adapter accepts only `localhost`, `127.0.0.1`, or `::1` origins and rejects embedded URL credentials | Services bound to loopback are not sandboxed; no DNS or network isolation is provided for CLI-launched programs |
| Request header contains credentials | Header values are not copied into the JSON report; only header names are recorded | The target service may echo credentials; paths, request bodies and responses remain user-controlled evidence and must be reviewed |
| Reset returns success without clearing state | Optional read-only health GET checks user-declared JSON Pointer assertions before the tested run | Only asserted fields are checked; this is not proof that every hidden or external state was reset |
| Workflow reorders a prerequisite | Explicit `depends_on` references are validated against named earlier steps; adjacent swaps avoid direct declared dependencies | Undeclared semantic dependencies remain unknown; step removal and duplication can still create invalid application-level workflows |
| Target is nondeterministic | Optional repeated runs can flag observed instability | Repetition cannot characterize every source of nondeterminism |

## Non-goals

TwinCheck is not a sandbox, antivirus product, exploit mitigation, malware analysis environment, or proof system. It does not make untrusted executables or local HTTP services safe to run. The HTTP adapter restricts requested origins to loopback addresses but does not isolate the target service, prevent that service from making outbound connections, or police CLI target networking. It does not currently enforce CPU or memory limits, filesystem boundaries, process-level outbound network policy, or temporary-storage quota.

## Guidance

- Only execute commands you trust and are authorized to test.
- Do not expose a web/API service that accepts arbitrary target commands or input corpora from untrusted users.
- Do not run third-party binaries in a sensitive environment simply because TwinCheck applies a timeout.
- Treat JSON reports as potentially sensitive: they include raw failing inputs and captured output. The HTTP adapter does not record request header values, but a response body or generated input can still reveal sensitive values.
- Before adding a container or OS-sandbox backend, define the threat boundary, default permissions, resource limits, host-platform behavior and escape-risk review. A container is isolation in depth, not an unconditional security guarantee.
- Report vulnerabilities privately through GitHub's security reporting flow if available, or contact the repository maintainer through a private channel.
