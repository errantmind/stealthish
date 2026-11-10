# Stealthish

A standalone browser CLI and async Python API for local AI workflows. Headless by default, persistent profiles, careful input, gorhill blocking, and manual updates.

**Current build: 0.1.0.dev5 — Linux development release with a Pi adapter.** The existing Pi extension selects an independently installed runtime after `/reload`. It retains its ownership queue; the product has no shared browser service. Windows validation, profile migration, and unattended updates remain deferred. Manual access uses the existing headed control, not a separate login command.

## Use the prepared instance

```sh
~/.local/share/stealthish/stealthish status
~/.local/share/stealthish/stealthish run
```

`run` accepts one JSON request per line. See [Pi instructions](docs/pi-browser.md) for `/reload`, manual access, and backend selection. See [operating instructions](docs/operating.md) for standalone setup, CLI/API examples, updates, and recovery. The older project-local `.local-data/` instance is not Pi's runtime.

Normal workflows use real websites. Python documentation and MDN worked through the installed product. **Kagi reached human verification; authenticated search remains unverified.** The early redirect exposed a pause-classification fault, corrected without retrying the challenge. No public Cloudflare acceptance is claimed.

Final local bot-detection integration runs retained practical acceptance in both startup orders. Known worker, scrolling, GPU, optional-API, and PDF limits remain. See [the latest results](docs/research/2026-11-11-pi-integration-results.md).

## Key documents

- [Pi browser instructions](docs/pi-browser.md)
- [Operating instructions](docs/operating.md)
- [Preserved concealment decisions](docs/concealment.md)
- [Manual updates](docs/manual-updates.md)
- [Runtime architecture](docs/runtime-architecture.md)
- [Product specification](docs/product-spec.md)
- [Remaining work](docs/roadmap.md)
- [Handoff](docs/HANDOFF.md)
- [Detector integration commands](docs/detector-checks.md)
- [Evidence index](docs/validation-plan.md)
- [Cleanup record](docs/cleanup.md)

## Layout

| Path | Purpose |
| --- | --- |
| `src/stealthish/` | Standalone product, acquisition, and foreground maintenance. |
| `src/stealthish_lab/`, `fixtures/` | Bot-detection integration support only; excluded from the product wheel. |
| `tools/` | Selected asset preparation and detector integration commands. |
| `docs/`, `docs/research/`, `evidence/` | Contracts, findings, historical results, and recorded hashes. |
| `pyproject.toml`, `uv.lock` | Packaging and pinned dependencies. |

Unit tests, fake Kagi, and general synthetic functional suites are not part of the project. Only bot-detection integration checks remain. Browser assets, profiles, backups, and raw output stay outside Git. Only the approved browser extension and backend selection changed. The original CloakBrowser profile and accounts were not imported or changed by this work.
