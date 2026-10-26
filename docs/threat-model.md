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
| Target modifies host or reaches the network | Documentation warns that targets run with current privileges | No filesystem, network, user, container, or syscall isolation |
| Target is nondeterministic | Optional repeated runs can flag observed instability | Repetition cannot characterize every source of nondeterminism |

## Non-goals

TwinCheck is not a sandbox, antivirus product, exploit mitigation, malware analysis environment, or proof system. It does not make untrusted executables safe to run. It does not currently enforce CPU or memory limits, filesystem boundaries, outbound network policy, or temporary-storage quota.

## Guidance

- Only execute commands you trust and are authorized to test.
- Do not expose a web/API service that accepts arbitrary target commands or input corpora from untrusted users.
- Do not run third-party binaries in a sensitive environment simply because TwinCheck applies a timeout.
- Treat JSON reports as potentially sensitive: they include raw failing inputs and captured output.
- Before adding a container or OS-sandbox backend, define the threat boundary, default permissions, resource limits, host-platform behavior and escape-risk review. A container is isolation in depth, not an unconditional security guarantee.
- Report vulnerabilities privately through GitHub's security reporting flow if available, or contact the repository maintainer through a private channel.
