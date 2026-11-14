# Stealthish

A foreground browser CLI and async Python API for local AI workflows: headless by default, persistent sign-ins, careful native input, and uBlock Origin Lite. Pi uses private pipes and its existing ownership queue—not a shared browser service.

## Install and use

At each backend startup, the Pi extension discovers the most recently published Stealthish release, including prereleases. It verifies the manifest and wheel against GitHub's asset digests, then acquires or reuses that release's pinned uv, managed Python, dependencies, private Chrome, and uBlock Origin Lite. No version pin in Pi, separate clone, system Python, PATH edit, or setup command is required. Updates preserve profile backups and side-by-side repair. Running sessions keep their release until restart. Lookup or setup failures are reported without selecting an older release.

[v0.1.0.dev8](https://github.com/errantmind/stealthish/releases/tag/v0.1.0.dev8) is a **Linux x86-64 prerelease** requiring glibc 2.31+, native browser libraries, and working Vulkan GPU support. It was measured on NVIDIA. Windows/macOS browser support is unfinished.

All nine Pi tools and `/browser` controls remain. Explicit headed access permits sign-in while automation is blocked. Existing profiles are not imported automatically. See the [Pi browser guide](https://github.com/errantmind/pi-extensions/blob/main/extensions/internet-browser/README.md) for setup and controls.

## Evidence and limits

Real Python-documentation/MDN browsing, concurrent first use, missing-browser repair, and local detector checks passed. Dev8 anonymous downloads, automatic installation from an empty directory, and the normal dev7-to-dev8 application update passed.

Live Kagi search returned 27 parsed results. The original failing query passed through Turnstile automatically and returned a confirmed empty result, without challenge input or a navigation retry. The local detector run retained the prior results, including bot-signal behavior at 0.30.

## Reference

- [Design](DESIGN.md).
- [Published releases](https://github.com/errantmind/stealthish/releases).
- [Pi extension](https://github.com/errantmind/pi-extensions/tree/main/extensions/internet-browser).

Detailed documentation and experiment records remain local in ignored `docs/` and `evidence/` directories.

`src/stealthish/` ships. Detector support in `src/stealthish_lab/` and `fixtures/` does not. `distribution/` and `tools/build_release.py` define releases. Profiles, binaries, environments, backups, and raw artifacts stay outside Git. Only detector integration tests are retained; ordinary workflow checks use real sites.
