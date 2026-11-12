# Design

Stealthish is a foreground CLI and async Python browser API for local AI workflows. Pi calls it through private pipes. Practical concealment and useful browsing are the priorities.

## Boundaries

- Headless by default. Explicit headed access permits manual use; automation stops until the user returns control. No automatic headed fallback, virtual display, login command, or credential subsystem.
- One persistent profile per computer, one foreground owner, one active operation. Conflicts return `PROFILE_BUSY` or `SESSION_BUSY`. Pi owns its queue outside the product; no shared browser service or network control port.
- Stealthish is the only backend. Existing legacy runtimes and profiles remain separate; there is no fallback or automatic credential migration.
- Positive challenge/authentication evidence pauses that site. Unrelated sites may continue. No challenge retries or automatic replay of actions with uncertain effects.

## Browser policy

Prefer published builds; browser-source changes require a separate decision. Preserve coherent Chrome identity, real GPU use where supported, platform-specific rendering, native storage partitioning, reviewed driver changes, `careful` input, the ARIA handle bridge, and key-release repair. Do not introduce rotating identities or page getter replacements merely to satisfy detectors.

Use uBlock Origin or uBlock Origin Lite; the current release uses Lite. Load verified files from a stable path; check settings and effective filtering without silent resets or disabling protection. Exact settings, rejected approaches, and limits belong in [concealment](docs/concealment.md).

## Installation and maintenance

The extension pins a complete release. Setup verifies and acquires official uv when needed, managed Python, dependencies, browser, and blocker. Repair uses a separate release directory. Activation retains exclusive ownership and matching profile recovery.

No independent latest-version lookup, background updater, or unpinned checkout fallback. See [automatic setup](docs/automatic-setup-plan.md), [publishing](docs/publishing.md), and [manual recovery](docs/manual-updates.md).

The release manifest lists supported OS/architecture combinations. Each platform needs native acquisition, lifecycle, rendering, and detector validation.

## Data and validation

Use the host connection without proxies. Keep profiles, credentials, input text, tokens, and raw artifacts outside Git and normal logs. Manual access blocks automated observation and input.

Retain only browser-level bot-detection integration suites. Normal workflows use real sites through the actual product—not fake Kagi, search APIs, substitute browsers, unit suites, or general fault-injection fixtures. Detector runs require verified network-namespace isolation and disabled BotD monitoring. Interception alone is insufficient. Keep detector rules unchanged; missing checks are not passes, and favorable random input must not be selected.

Preserve measured findings, rejected approaches, and compact evidence. Deleted raw-run limits are documented. Archives are not runtime dependencies; do not restore obsolete tests as requirements. See [detector checks](docs/detector-checks.md).

## Repository responsibilities

- `src/stealthish/`: shipped product. `src/stealthish_lab/`, `fixtures/`, and detector tools: unshipped integration support. `distribution/`: publication inputs.
- [Handoff](docs/HANDOFF.md) records current state; [roadmap](docs/roadmap.md) records remaining work. This document contains stable design decisions.

See [architecture](docs/runtime-architecture.md) for modules, [specification](docs/product-spec.md) for contracts, and [Pi](docs/pi-browser.md)/[standalone](docs/operating.md) guides for operation.
