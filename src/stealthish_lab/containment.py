"""Linux test containment. Fail closed on unsupported or incomplete isolation."""

from __future__ import annotations

import errno
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


class ContainmentError(RuntimeError):
    pass


def namespace(name: str) -> str:
    return os.readlink(f"/proc/self/ns/{name}")


def validate_network(links: list[dict], routes: list[dict]) -> None:
    if len(links) != 1 or links[0].get("ifname") != "lo":
        raise ContainmentError("The network must contain only loopback.")
    if "UP" not in links[0].get("flags", []):
        raise ContainmentError("Loopback is not up.")
    for route in routes:
        try:
            loopback = ipaddress.ip_network(route.get("dst", ""), strict=False).is_loopback
        except ValueError:
            loopback = False
        if route.get("dev") != "lo" or route.get("type") not in ("local", "broadcast") or not loopback:
            raise ContainmentError("The network has a non-local route.")


def sandbox_command(root: Path, run: Path, child_args: list[str]) -> list[str]:
    if sys.platform != "linux":
        raise ContainmentError("Native Windows containment is not implemented. No browser was started.")
    root, run = root.resolve(), run.resolve()
    if not run.is_relative_to(root / ".runtime") or run == root / ".runtime":
        raise ContainmentError("The writable run directory must be inside .runtime.")
    # The source and dependencies are read-only. Only this run can be changed.
    # Hide host home directories and session sockets. Keep real GPU devices.
    return [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--ro-bind", "/", "/", "--tmpfs", "/home", "--tmpfs", "/root",
        "--tmpfs", "/run", "--tmpfs", "/tmp", "--proc", "/proc",
        "--dev-bind", "/dev", "/dev", "--tmpfs", "/dev/shm",
        "--ro-bind", str(root), str(root), "--bind", str(run), str(run),
        "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", str(run / "home"),
        "--setenv", "XDG_CONFIG_HOME", str(run / "home/config"),
        "--setenv", "XDG_CACHE_HOME", str(run / "home/cache"),
        "--setenv", "XDG_RUNTIME_DIR", str(run / "home/run"),
        "--setenv", "PYTHONPATH", str(root / "src"),
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONNOUSERSITE", "1", "--setenv", "LANG", "C.UTF-8",
        "--setenv", "LC_ALL", "C.UTF-8", "--chdir", str(root), "--",
        str(root / ".venv/bin/python"), "-B", *child_args,
    ]


def preflight(host_namespaces: dict[str, str], canary_port: int, root: Path) -> dict:
    if sys.platform != "linux":
        raise ContainmentError("Linux containment is required for this runner.")
    current = {name: namespace(name) for name in ("net", "pid", "mnt", "user")}
    if any(current[name] == host_namespaces[name] for name in current):
        raise ContainmentError("A required namespace is shared with the host.")
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        raise ContainmentError("A display variable is present.")
    if any(key.lower().endswith("proxy") for key in os.environ):
        raise ContainmentError("A proxy variable is present.")
    links = json.loads(subprocess.check_output(["ip", "-j", "address"], text=True))
    routes = []
    for family in ("-4", "-6"):
        routes += json.loads(subprocess.check_output(
            ["ip", family, "-j", "route", "show", "table", "all"], text=True
        ))
    validate_network(links, routes)
    # Production homes are hidden. No host desktop/session sockets may be visible.
    host_home = root.parents[2]
    if (host_home / ".pi").exists() or list(Path("/run").iterdir()):
        raise ContainmentError("Host profile or session paths are visible.")
    attempts = []
    for family, kind, address, port in (
        (socket.AF_INET, socket.SOCK_STREAM, "192.0.2.1", 80),
        (socket.AF_INET, socket.SOCK_STREAM, "192.0.2.1", 443),
        (socket.AF_INET, socket.SOCK_DGRAM, "192.0.2.53", 53),
        (socket.AF_INET, socket.SOCK_DGRAM, "192.0.2.1", 3478),
        (socket.AF_INET6, socket.SOCK_STREAM, "2001:db8::1", 443),
    ):
        try:
            with socket.socket(family, kind) as client:
                client.settimeout(1)
                if kind == socket.SOCK_DGRAM:
                    client.sendto(b"stealthish-local-egress-test", (address, port))
                else:
                    client.connect((address, port))
        except OSError as error:
            if error.errno not in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EAFNOSUPPORT):
                raise ContainmentError(f"Unexpected network result: {error.errno}") from error
            attempts.append({"address": address, "port": port, "errno": error.errno,
                             "status": "UNSUPPORTED" if error.errno == errno.EAFNOSUPPORT else "BLOCKED_BY_POLICY"})
        else:
            raise ContainmentError("An external address was reachable. Stop the run.")
    with socket.socket() as client:
        client.settimeout(1)
        result = client.connect_ex(("127.0.0.1", canary_port))
        if result != errno.ECONNREFUSED:
            raise ContainmentError("The host-loopback sentinel check did not fail as required.")
    # UDP must also remain in the isolated namespace. The outer observer checks receipt.
    with socket.socket(type=socket.SOCK_DGRAM) as client:
        client.sendto(b"stealthish-local-egress-test", ("127.0.0.1", canary_port))
    return {
        "status": "PASS", "method": "bubblewrap-user-pid-mount-network-namespaces",
        "namespaces": current, "links": links, "routes": routes, "deniedSocketAttempts": attempts,
        "hostLoopbackTCP": "ECONNREFUSED", "hostLoopbackUDP": "outer observer required",
        "display": "absent", "hostProfilePaths": "hidden",
    }


def process_evidence(profile: Path) -> dict:
    """Inspect only processes that are visible inside the isolated PID namespace."""
    entries = []
    expected_net = namespace("net")
    browser_found = False
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            raw = (process / "cmdline").read_bytes()
            args = raw.decode(errors="replace").rstrip("\0").split("\0")
            if not raw:
                continue
            net = os.readlink(process / "ns/net")
            env = (process / "environ").read_bytes().split(b"\0")
            is_browser = f"--user-data-dir={profile}" in args
            if is_browser:
                browser_found = True
                if "--headless" not in args or "--no-sandbox" in args:
                    raise ContainmentError("The browser is not sandboxed true headless.")
            if net != expected_net:
                # Chromium can create a stricter network namespace for sandboxed children.
                # Inspect those namespaces and reject any with a non-loopback interface/route.
                dev = (process / "net/dev").read_text()
                routes = (process / "net/route").read_text().splitlines()[1:]
                ipv6 = (process / "net/ipv6_route").read_text().splitlines()
                interfaces = [line.split(":", 1)[0].strip() for line in dev.splitlines()[2:]]
                if any(name != "lo" for name in interfaces) or routes or any(
                    line.split()[-1] != "lo" for line in ipv6
                ):
                    raise ContainmentError("A child has unexpected network access.")
            if any(value.startswith((b"DISPLAY=", b"WAYLAND_DISPLAY=")) for value in env):
                raise ContainmentError("A child process has a display variable.")
            entries.append({"pid": int(process.name), "executable": args[0],
                            "networkNamespace": net, "browserMain": is_browser,
                            "arguments": args if is_browser else None})
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            # Sandbox child metadata can be restricted. Do not call it verified.
            entries.append({"pid": int(process.name), "status": "UNSUPPORTED",
                            "reason": "Sandbox child metadata is not readable."})
    if not browser_found:
        raise ContainmentError("No matching browser process was found.")
    return {"status": "PASS", "processes": entries,
            "limit": "Restricted child metadata is listed, not treated as a direct observation."}
