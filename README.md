# Stealthish

A stealthy browser interface for local Agents. I built this for myself after Cloakbrowser went paid as a replacement. I integrate it into Pi Agent using a separate extension. The interface is simple enough for it to be used or integrated into any Agent Harness.

A foreground browser CLI and async Python API for local AI workflows: headless by default, persistent sign-ins, careful native input, and uBlock Origin Lite. Pi uses private pipes and its existing ownership queue—not a shared browser service.

## Install and use

At each backend startup, a Pi Agent extension discovers the most recently published Stealthish release, including prereleases. It verifies the manifest and wheel against GitHub's asset digests, then acquires or reuses that release's pinned uv, managed Python, dependencies, private Chrome, and uBlock Origin Lite. No version pin in Pi, separate clone, system Python, PATH edit, or setup command is required. Updates preserve profile backups and side-by-side repair. Running sessions keep their release until restart. Lookup or setup failures are reported without selecting an older release.

[v0.1.0.dev8](https://github.com/errantmind/stealthish/releases/tag/v0.1.0.dev8) is a **Linux x86-64 prerelease** requiring glibc 2.31+, native browser libraries, and working Vulkan GPU support. It was measured on NVIDIA. Windows/macOS browser support is unfinished.

All nine Pi tools and `/browser` controls remain. Explicit headed access permits sign-in while automation is blocked. Existing profiles are not imported automatically. See the [Pi browser guide](https://github.com/errantmind/pi-extensions/blob/main/extensions/internet-browser/README.md) for setup and controls.

## Evidence and limits

Passes bot checks undetected.

## Reference

- [Design](DESIGN.md).
- [Published releases](https://github.com/errantmind/stealthish/releases).
- [Pi extension](https://github.com/errantmind/pi-extensions/tree/main/extensions/internet-browser).

Detailed documentation and experiment records remain local in ignored `docs/` and `evidence/` directories.

`src/stealthish/` ships. Detector support in `src/stealthish_lab/` and `fixtures/` does not. `distribution/` and `tools/build_release.py` define releases. Profiles, binaries, environments, backups, and raw artifacts stay outside Git. Only detector integration tests are retained; ordinary workflow checks use real sites.
