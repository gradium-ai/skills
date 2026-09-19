# Security scope

This is experimental, trusted-local browser automation. It is not a sandbox, a permissions system, a multi-tenant service, or a guarantee against prompt injection. Do not run it against arbitrary user-supplied tasks in a server connected to privileged accounts or internal networks.

## Data and authority

- Jev uses the Chrome profile connected to Browser Harness. Cookies and logged-in accounts can authorize actions. Use a dedicated automation profile; the runner does not create or enforce that separation. Keep debugging access private. Chrome's guidance recommends isolating debugging from real profiles: https://developer.chrome.com/blog/remote-debugging-port
- Autonomous execution requires `--allow-actions`. This explicitly opts into actions and model calls, but does not implement per-action approval or a read-only action allowlist. Even an ordinary link or text field can trigger an external mutation. Task wording is not an enforcement boundary.
- Jev sends goals, observed page text, URLs, control values, and recent action context to TypeSafe. Typing sends additional context to the configured text provider. Local log minimization does not alter these upstream requests. Do not delegate authentication, secrets, payments, or sensitive accounts to this tool. Handle any required human confirmation outside the autonomous loop.
- `--inspect-only` does not call a model or dispatch intentional browser input. Opening a URL still sends browser requests, credentials/cookies where applicable, and executes site JavaScript. Existing-session inspection evaluates fixed code in the page context; malicious page code can influence observations. It is not a security-isolated DOM reader.
- HTTP(S) URL validation rejects ambiguous syntax and embedded credentials. Exact expected frame URLs prevent simple index drift. Neither feature is a network policy: redirects, subresources, private-network destinations, and subsequent agent navigation are not restricted. Use OS/network controls if stronger isolation is needed.

## Logs and credentials

Default output contains status, counts, and check outcomes. `--include-page-content` reveals text, labels and full URLs, potentially including personal data and tokens. `--include-field-values` additionally reveals ordinary form values. Password/file fields are excluded or redacted where directly identified, but secrets displayed in normal text or labels are not reliably detectable. Do not publish raw output.

`--output` creates a new file with mode 0600 and rejects existing files/symlinks; stdout remains a summary. Use a trusted private parent directory. POSIX mode is not a guarantee of Windows ACL privacy. The host assistant may retain tool output in its own logs.

Store provider keys in a private environment or protected `.env`, never in chat, goals, source, or command-line flags. Use HTTPS for the text-model endpoint; the runner rejects a configured plaintext endpoint when a text key is present. Confirm that the chosen endpoint belongs to the intended provider: HTTPS does not establish organizational trust. Rotate exposed keys and use least-privilege credentials and provider spending limits.

## Resource and dependency limits

Tick/time budgets are cooperative, checked between operations. They are not a hard timeout or a spending cap. Interrupted operations may already have changed state; never automatically replay a task.

The setup pins upstream commit `1231850a0bf1a0c0341fe408ef1668dbbfdfac46` and uses its frozen lock without development dependencies. Updates require a new review. A dependency advisory scan is not a review of dependency source, package provenance, Chrome security, or model behavior.

On 2026-09-19, the 12 registry packages in the pinned runtime dependency closure had no known advisories in the pip-audit scan. The full lock's development dependency pytest 8.4.2 is affected by CVE-2025-71176 (fixed in 9.0.3): https://github.com/advisories/GHSA-6w46-j5rx-g56g . The documented `--no-dev` setup/run commands avoid installing that package. The wrapper's tests use unittest, not pytest. Upstream's development lock was not patched.

## Reporting

Do not put credentials, cookies, private page captures, or personal data in public issues. Report suspected vulnerabilities through a private maintainer channel where available. Before publishing this project, the maintainer should configure private vulnerability reporting or add a monitored security contact here. No private reporting channel is configured by this template.
