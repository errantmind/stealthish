# Stealthish

A standalone browser CLI and async Python API for local AI workflows. Headless by default, persistent profiles, careful native input, and gorhill blocking. The Pi extension uses private pipes and its existing ownership queue, not a shared browser service.

**Current release: [v0.1.0.dev6](https://github.com/errantmind/stealthish/releases/tag/v0.1.0.dev6), a Linux prerelease.** Automatic setup is checked locally, and anonymous downloads of the published assets match their pinned hashes. A complete fresh installation using those public assets remains to be checked. See [publishing](docs/publishing.md).

## Automatic Pi setup

The extension pins the published release. Its first browser request installs any missing components and continues the request:

```text
Official pinned uv installer, if needed
    -> managed Python and locked application wheels
    -> exact private Chrome and gorhill packages
    -> profile-safe activation and readiness
    -> requested browsing action
```

No separate Stealthish clone, system Python, PATH edit, backend-selection setting, or setup command. Later starts verify and reuse the release. A changed extension pin activates a prepared release with matching profile recovery; damaged private files receive a separate repair copy. There is no independent latest-version updater or legacy backend fallback.

The current manifest supports **Linux x86-64 with glibc 2.31+, native browser libraries, and working Vulkan GPU support**. The measured host uses NVIDIA. Windows/macOS browser ports and native validation remain unfinished. Official uv installer branches alone are not browser support.

## Use and evidence

All nine Pi browser tools and `/browser` controls remain. Explicit headed access permits human sign-in; automation is blocked until control returns. Existing account profiles are not imported automatically. Standalone CLI/API and manual recovery remain available.

Real Python documentation and MDN use passed through automatic setup and the registered adapter. Two concurrent clients performed one installation and then browsed in sequence. Missing-browser repair worked. Two local detector runs using the managed runtime retained the earlier practical six-suite results, including behavioral acceptance at 0.30.

**Kagi authentication and public Cloudflare acceptance remain unverified.** No challenge retry or public detector request was made. Keep known worker, scrolling, GPU, optional-API, and PDF limits explicit.

## Documents

- [Design decisions and development boundaries](DESIGN.md)
- [Publication and automatic setup](docs/publishing.md)
- [Pi instructions](docs/pi-browser.md)
- [Standalone operating instructions](docs/operating.md)
- [Latest setup results](docs/research/2026-11-11-automatic-setup-results.md)
- [Preserved concealment decisions](docs/concealment.md)
- [Runtime architecture](docs/runtime-architecture.md)
- [Product specification](docs/product-spec.md)
- [Manual recovery procedure](docs/manual-updates.md)
- [Remaining work](docs/roadmap.md)
- [Handoff](docs/HANDOFF.md)
- [Bot-detection integration commands](docs/detector-checks.md)

`src/stealthish/` is the product. `src/stealthish_lab/` and `fixtures/` contain only detector integration support and are not shipped. `distribution/` and `tools/build_release.py` define publication inputs. Browser binaries, environments, profiles, backups, and raw outputs stay outside Git.

No unit tests, fake Kagi pages, or general synthetic website suites. Normal workflow checks use real sites. The original installed profile and accounts remain unchanged by this development.
