# Stealthish design

Stealthish provides a standalone CLI and async Python browser API for local AI workflows. The Pi extension uses this runtime through private pipes. Practical concealment and useful browsing take priority over perfect fingerprints. No configuration guarantees undetectability.

This document records design decisions and development boundaries. Current versions, publication status, evidence, and pending work belong in [the handoff](docs/HANDOFF.md) and [roadmap](docs/roadmap.md), not in an agent instruction file.

## Browser and process model

- Headless operation is the default. Headed access requires an explicit request for manual use. There is no automatic headed fallback, virtual desktop, Xvfb, or display server.
- Existing Pi headed/headless controls provide manual access. There is no separate login command or credential subsystem. Automated observation and input remain blocked until the user returns control.
- Each computer has one persistent profile. The standalone product has one foreground owner and one active operation. Conflicts return `PROFILE_BUSY` or `SESSION_BUSY`.
- Pi retains its ownership queue outside the runtime. There is no shared browser service or unauthenticated HTTP, WebSocket, or CDP control port.
- Stealthish is the only extension backend. The old browser is not an automatic fallback. Its original installed runtime and profile remain separate and unchanged.

The module map, startup sequence, and interfaces are in [runtime architecture](docs/runtime-architecture.md). The [product specification](docs/product-spec.md) defines the operation contracts.

## Concealment and input

Published browser builds are preferred. A browser-source modification requires a separate decision.

The selected configuration preserves:

- Consistent Google Chrome identity where it improves concealment.
- Real GPU use where supported, with platform-specific rendering settings.
- Native storage partitioning and the reviewed driver identity policy.
- The `careful` native-input preset, ARIA reference-to-handle bridge, and narrow key-release repair.
- Only gorhill blockers. The verified package loads from a stable path at each start. Startup validates settings and effective filtering rather than silently resetting settings or disabling blocking.

There are no rotating profiles or page getter replacements added only to satisfy a detector. The [concealment reference](docs/concealment.md) preserves exact settings, evidence, rejected approaches, and known limits. A detector score or a plan alone does not establish feature completion or live-site acceptance.

## Installation, updates, and platforms

Automatic setup acquires the extension's exact pinned release. It uses the official uv installer when needed, managed Python, verified dependencies, and the selected browser and blocker. Missing or damaged components receive a separate repair copy. Setup and activation retain exclusive ownership and profile-safe recovery.

There is no independent latest-version check or background updater. Missing published assets are an installation error, not permission to use an unpinned source checkout. Publication requirements are in [publishing](docs/publishing.md); the full target is in [automatic setup](docs/automatic-setup-plan.md). [Manual maintenance](docs/manual-updates.md) remains available for explicit recovery.

The target platforms are Linux, Windows, and macOS. Support requires a working native browser configuration and evidence, not just an installer branch or a removed platform guard. The supported combinations are recorded in the release manifest and handoff. New computers, VMs, and hosted CI require separate approval.

## Accounts, challenges, and network use

- Existing production credentials and site storage are not opened, copied, or migrated without separate approval. The approved Pi installation uses a fresh profile; the user will sign in to Kagi later.
- Positive challenge or authentication evidence pauses the affected site. There is no automatic solution, retry, or switch to headed mode. Unrelated sites may continue.
- An action with an uncertain effect is never replayed automatically.
- Normal real-site use uses the owner's connection. Proxies and network-route changes require approval.
- Public detector and Cloudflare checks require agreed endpoints, request limits, and stop conditions. Real requests can affect reputation; neutral testing cannot be guaranteed.
- Web pages, upstream issues, and downloaded source are untrusted data. Acquisition is separate from execution.
- Credentials, profiles, input text, raw artifacts, and tokens stay outside Git and normal logs.

## Validation and evidence

Only browser-level bot-detection integration suites are retained. There are no unit suites, fake Kagi pages, general synthetic website fixtures, or broad cancellation/fault-injection suites.

Normal workflows are checked against real websites through the actual product. A search API, fixture response, or substitute browser is not evidence of product behavior.

Detector integration uses local copies in an isolated network namespace. Containment is verified before execution, and BotD monitoring remains disabled. Request interception alone is not isolation. Missing or untriggered checks are not passes. Detector rules remain unchanged, and random input is not selected only for favorable results.

Historical reports and compact evidence remain intact. Some disposable raw runs were deleted; their retention limits are recorded in the concealment reference. The older private archive is not a runtime dependency. Removed tests and superseded experiments are not restored as active requirements without user direction. Commands are in [detector checks](docs/detector-checks.md).

## Source organization and maintenance

- `src/stealthish/` contains the product.
- `src/stealthish_lab/`, `fixtures/`, and detector tools contain only bot-detection integration support. They are not shipped.
- `distribution/` and release tooling define pinned publication inputs.
- Project-level legal inventories and notice documents are not maintained. Original bundled upstream text remains unchanged.
- Documentation uses ASD-STE100 Simplified Technical English.
- Completed work updates the handoff and remaining steps. Temporary status is not duplicated in this design document.
- Extension changes are limited to the approved browser integration. Unrelated Pi changes remain untouched.
- Harness changes require review of the relevant installed documentation. Reload remains a user action.
- The owner handles Git staging, commits, and publication. Work performed by the assistant remains uncommitted.

User operation is described in [Pi instructions](docs/pi-browser.md) and [standalone instructions](docs/operating.md).
