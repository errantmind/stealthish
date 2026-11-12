# Stealthish

A foreground browser CLI and async Python API for local AI workflows: headless by default, persistent sign-ins, careful native input, and uBlock Origin Lite. Pi uses private pipes and its existing ownership queue—not a shared browser service.

## Install and use

The Pi extension automatically acquires its pinned release on first use: official uv when needed, managed Python, locked wheels, private Chrome, and uBlock Origin Lite. No separate clone, system Python, PATH edit, or setup command is required. Later starts verify and reuse files; updates follow the extension pin, with profile backup and side-by-side repair. No legacy fallback or independent latest-version updater.

[v0.1.0.dev6](https://github.com/errantmind/stealthish/releases/tag/v0.1.0.dev6) is a **Linux x86-64 prerelease** requiring glibc 2.31+, native browser libraries, and working Vulkan GPU support. It was measured on NVIDIA. Windows/macOS browser support is unfinished.

All nine Pi tools and `/browser` controls remain. Explicit headed access permits sign-in while automation is blocked. Existing profiles are not imported automatically. See [Pi use](docs/pi-browser.md) or [standalone CLI/API use](docs/operating.md).

## Evidence and limits

Real Python-documentation/MDN browsing, concurrent first use, missing-browser repair, and two managed-runtime detector runs passed in the measured scope. Anonymous release downloads match their pins; a complete fresh installation from public assets remains unchecked.

Kagi authentication and Cloudflare checks remain pending. Worker, scrolling, GPU, optional-API, and PDF results are recorded in [concealment](docs/concealment.md) and [setup results](docs/research/2026-11-11-automatic-setup-results.md).

## Reference

- [Design](DESIGN.md), [architecture](docs/runtime-architecture.md), [operation contracts](docs/product-spec.md).
- [Publication](docs/publishing.md), [maintenance/recovery](docs/manual-updates.md).
- [Handoff](docs/HANDOFF.md), [remaining work](docs/roadmap.md), [detector commands](docs/detector-checks.md).

`src/stealthish/` ships. Detector support in `src/stealthish_lab/` and `fixtures/` does not. `distribution/` and `tools/build_release.py` define releases. Profiles, binaries, environments, backups, and raw artifacts stay outside Git. Only detector integration tests are retained; ordinary workflow checks use real sites.
