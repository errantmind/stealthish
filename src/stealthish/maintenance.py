"""Foreground preparation, activation, and profile-safe recovery. No updater service."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import uuid
import venv

from .acquire import acquire
from .compatibility import adapt_driver
from .config import RELEASE_ID, SessionConfig
from .errors import StartupError
from .ownership import ProfileLock, private_directory
from .release import (VERSION, BROWSER_VERSION, BLOCKER_VERSION, DRIVER_VERSION,
                      DEPENDENCIES, child, digest, verify_files)

MARKER = "state/maintenance-in-progress.json"


def write_file(path: Path, data: bytes):
    private_directory(path.parent)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    write_file(path, (json.dumps(value, indent=2) + "\n").encode())


def config_bytes(config):
    values = {"schema_version": 1, **asdict(config)}
    values["data_dir"] = str(config.data_dir)
    return ("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n").encode()


def hashes(root):
    return {p.relative_to(root).as_posix(): digest(p)
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def require_linux():
    import platform
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise StartupError("UNSUPPORTED_PLATFORM")


def release_path(root, name):
    if not isinstance(name, str) or not RELEASE_ID.fullmatch(name):
        raise StartupError("INVALID_CONFIG")
    return child(root / "releases", name)


def environment(release):
    """Copy only the installed, pinned distributions into a new fixed-path venv."""
    expected = {"stealthish": VERSION, **DEPENDENCIES}
    distributions = []
    for name, wanted in expected.items():
        dist = metadata.distribution(name)
        if dist.version != wanted or not dist.files:
            raise StartupError("RELEASE_INVALID")
        direct = dist.read_text("direct_url.json")
        if direct and json.loads(direct).get("dir_info", {}).get("editable"):
            raise StartupError("RELEASE_INVALID")
        distributions.append(dist)
    target = release / "env"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(target)
    site = target / Path(sysconfig.get_path("purelib")).relative_to(sys.prefix)
    private_directory(site)
    for dist in distributions:
        base = Path(dist.locate_file("")).resolve()
        for entry in dist.files:
            # Console scripts are outside site-packages. The product runs with -m.
            if ".." in entry.parts or "__pycache__" in entry.parts or str(entry).endswith(".pyc"):
                continue
            source = Path(dist.locate_file(entry))
            if source.is_symlink() or not source.resolve().is_relative_to(base):
                raise StartupError("RELEASE_INVALID")
            destination = child(site, str(entry))
            private_directory(destination.parent)
            shutil.copy2(source, destination)
    package = site / "stealthish"
    if hashes(package) != hashes(Path(__file__).parent):
        raise StartupError("RELEASE_INVALID")
    return site


def prepare(data_dir: Path, name: str):
    require_linux()
    root = data_dir.expanduser().resolve()
    with ProfileLock(root):
        if (root / MARKER).exists():
            raise StartupError("MAINTENANCE_REQUIRED")
        target = release_path(root, name)
        if target.exists():
            raise StartupError("RELEASE_EXISTS")
        private_directory(target)
        try:
            provenance = acquire(root / "downloads", target)
            import patchright
            driver = Path(patchright.__file__).parent / "driver"
            shutil.copytree(driver / "package", target / "driver/package")
            shutil.copy2(driver / "node", target / "driver/node")
            bundle = target / "driver/package/lib/coreBundle.js"
            bundle.write_bytes(adapt_driver(bundle.read_bytes()))
            site = environment(target)
            manifest = {
                "schemaVersion": 1, "release": name, "appVersion": VERSION,
                "platform": "linux", "architecture": "x86_64",
                "browserExecutable": "chrome", "browserVersion": BROWSER_VERSION,
                "driverVersion": DRIVER_VERSION, "blockerVersion": BLOCKER_VERSION,
                "dependencyVersions": DEPENDENCIES,
                "files": {area: hashes(target / area) for area in ("browser", "driver", "blocker")},
                "runtimeFiles": hashes(Path(__file__).parent),
                "environmentPath": site.relative_to(target).as_posix(),
                "environmentFiles": hashes(site), "pythonVersion": sys.version.split()[0],
                "provenance": provenance,
                "validation": {"status": "PREPARED", "liveSites": "NOT_CHECKED", "windows": "DEFERRED"},
            }
            write_json(target / "manifest.json", manifest)
        except BaseException:
            # This new directory has never been selected and contains no user profile.
            shutil.rmtree(target)
            raise
    return {"code": "OK", "release": name, "appVersion": VERSION, "selected": False,
            "next": "Activate explicitly. No browser or existing profile was opened."}


def inventory(root):
    result = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = {"link": os.readlink(path)}
        elif path.is_file():
            result[name] = {"sha256": digest(path)}
        elif path.is_dir():
            result[name] = {"directory": True}
        else:
            raise StartupError("BACKUP_FAILED")
    return result


def copy_state(source, target):
    if source.is_symlink():
        raise StartupError("BACKUP_FAILED")
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        private_directory(target.parent)
        shutil.copy2(source, target)


def sync_tree(root):
    """Finish backup writes before recording that active state may change."""
    for directory, _, files in os.walk(root, followlinks=False, topdown=False):
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                with path.open("rb") as source:
                    os.fsync(source.fileno())
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def backup(root):
    profile_lock = root / "profile/SingletonLock"
    if profile_lock.exists() or profile_lock.is_symlink():
        raise StartupError("PROFILE_BUSY")
    saved = root / "recovery" / stamp()
    private_directory(saved)
    names = ("profile", "blocker", "config.toml", "state/blocker.json")
    present = []
    try:
        for name in names:
            source = root / name
            if source.exists():
                copy_state(source, saved / name)
                present.append(name)
        recorded = inventory(saved)
        # Compare each source with its copy before any active state changes.
        for name in present:
            source, copied = root / name, saved / name
            if source.is_dir():
                if inventory(source) != inventory(copied):
                    raise StartupError("BACKUP_FAILED")
            elif digest(source) != digest(copied):
                raise StartupError("BACKUP_FAILED")
        sync_tree(saved)
        write_json(saved / "backup.json", {"present": present, "files": recorded})
    except BaseException:
        # Keep an incomplete copy for inspection; it is never selected for recovery.
        raise StartupError("BACKUP_FAILED") from None
    return {"backup": saved.name, "sha256": digest(saved / "backup.json")}


def verify_backup(root, record):
    saved = child(root / "recovery", record["backup"])
    if digest(saved / "backup.json") != record["sha256"]:
        raise StartupError("BACKUP_FAILED")
    data = json.loads((saved / "backup.json").read_text())
    actual = inventory(saved)
    actual.pop("backup.json", None)
    if actual != data["files"]:
        raise StartupError("BACKUP_FAILED")
    if set(data["present"]) - {"profile", "blocker", "config.toml", "state/blocker.json"}:
        raise StartupError("BACKUP_FAILED")
    return saved, data["present"]


def verify_startup(root, name, lock, *, initialize=False):
    release = release_path(root, name)
    python = release / "env/bin/python"
    if not python.is_file():
        raise StartupError("RELEASE_INVALID")
    command = [str(python), "-I", "-B", "-m", "stealthish", "_verify",
               "--data-dir", str(root), "--release", name, "--owner-fd", str(lock.fd)]
    if initialize:
        command.append("--initialize")
    try:
        result = subprocess.run(command, pass_fds=(lock.fd,), capture_output=True,
                                timeout=180, check=False)
    except subprocess.TimeoutExpired:
        raise StartupError("MAINTENANCE_REQUIRED") from None
    if result.returncode:
        # Raw driver errors and profile details are not copied into normal output.
        raise StartupError("MAINTENANCE_REQUIRED")


async def verify_child(root, name, fd, initialize):
    from .session import BrowserSession
    lock = ProfileLock.adopt(root, fd)
    session = BrowserSession(SessionConfig(root, name))
    try:
        await session._maintenance_open(lock, initialize=initialize)
    finally:
        await session.close()
        lock.close()


def launcher(root):
    # The launcher selects an immutable release environment. It has no browser logic.
    data = '''#!/usr/bin/env python3
import os
from pathlib import Path
import re
import sys
import tomllib
root = Path(__file__).resolve().parent
try:
    name = tomllib.loads((root / "config.toml").read_text())["release"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name):
        raise ValueError()
    python = root / "releases" / name / "env/bin/python"
    args = sys.argv[1:] or ["status"]
    os.execv(python, [str(python), "-I", "-B", "-m", "stealthish", *args, "--data-dir", str(root)])
except (OSError, KeyError, ValueError):
    sys.exit("No usable selected release. Use explicit setup or recovery.")
'''
    write_file(root / "stealthish", data.encode())
    (root / "stealthish").chmod(0o700)


def activate(data_dir: Path, name: str):
    require_linux()
    root = data_dir.expanduser().resolve()
    with ProfileLock(root) as lock:
        if (root / MARKER).exists():
            raise StartupError("MAINTENANCE_REQUIRED")
        target = release_path(root, name)
        manifest = json.loads((target / "manifest.json").read_text())
        if (manifest.get("release") != name or manifest.get("schemaVersion") != 1
                or set(manifest.get("files", {})) != {"browser", "driver", "blocker"}):
            raise StartupError("RELEASE_INVALID")
        # Verify candidate files before changing the active installation.
        for area, files in manifest["files"].items():
            if area not in {"browser", "driver", "blocker"}:
                raise StartupError("RELEASE_INVALID")
            verify_files(target / area, files)
        verify_files(child(target, manifest["environmentPath"]), manifest["environmentFiles"], ignore_bytecode=True)
        old = SessionConfig.load(root / "config.toml") if (root / "config.toml").exists() else None
        if old and (old.data_dir != root or old.release == name):
            raise StartupError("INVALID_CONFIG")
        if not old and ((root / "profile").exists() and any((root / "profile").iterdir())):
            raise StartupError("INVALID_CONFIG")
        record = backup(root)
        record.update({"candidate": name, "previous": old.release if old else None})
        write_json(root / MARKER, record)
        blocker = root / "blocker"
        if blocker.exists():
            shutil.rmtree(blocker)
        shutil.copytree(target / "blocker", blocker)
        config = replace(old, release=name) if old else SessionConfig(root, name)
        write_file(root / "config.toml", config_bytes(config))
        if old:
            marker = json.loads((root / "state/blocker.json").read_text())
            marker["version"] = manifest["blockerVersion"]
            write_json(root / "state/blocker.json", marker)
        verify_startup(root, name, lock, initialize=old is None)
        write_json(root / "state/previous.json", record)
        launcher(root)
        (root / MARKER).unlink()
    return {"code": "OK", "release": name, "previous": record["previous"],
            "launcher": str(root / "stealthish"), "recovery": record["backup"],
            "next": "Use real browsing tasks. Startup did not prove account or live-site acceptance."}


def recover(data_dir: Path, *, accept_data_loss=False):
    require_linux()
    if not accept_data_loss:
        raise StartupError("RECOVERY_CONFIRMATION_REQUIRED")
    root = data_dir.expanduser().resolve()
    with ProfileLock(root) as lock:
        pending = root / MARKER
        record_path = pending if pending.exists() else root / "state/previous.json"
        if not record_path.exists():
            raise StartupError("NO_RECOVERY")
        record = json.loads(record_path.read_text())
        if record.get("restored"):
            raise StartupError("NO_RECOVERY")
        saved, present = verify_backup(root, record)
        profile_lock = root / "profile/SingletonLock"
        if profile_lock.exists() or profile_lock.is_symlink():
            raise StartupError("PROFILE_BUSY")
        write_json(pending, record)
        # Preserve post-update data rather than erase it. Repeating interrupted
        # recovery creates another kept copy, then restores the same verified backup.
        failed = root / "recovery" / ("kept-" + stamp())
        private_directory(failed)
        for name in ("profile", "blocker", "config.toml", "state/blocker.json"):
            source = root / name
            if source.is_symlink():
                raise StartupError("BACKUP_FAILED")
            if source.exists():
                destination = failed / name
                private_directory(destination.parent)
                source.rename(destination)
            if name in present:
                copy_state(saved / name, source)
        if record["previous"] is not None:
            verify_startup(root, record["previous"], lock)
            launcher(root)
        write_json(root / "state/previous.json", {**record, "restored": True})
        pending.unlink()
    return {"code": "OK", "release": record["previous"], "preservedState": str(failed),
            "warning": "Recovery restores the backup time. Later site changes are not in the active profile."}
