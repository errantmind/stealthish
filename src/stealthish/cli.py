"""Foreground JSON-lines interface. No listeners or background workers."""
import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import sys

from .config import SessionConfig, default_paths
from .errors import StealthishError
from .ownership import ProfileLock
from .protocol import CAPABILITIES, MAX_LINE, Request, Result
from .release import child, load_release, verify_files
from .session import BrowserSession


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    sys.stdout.flush()


def status(config):
    lock = ProfileLock(config.data_dir)
    busy = False
    try:
        lock.acquire()
    except StealthishError as error:
        if error.code != "PROFILE_BUSY":
            raise
        busy = True
    try:
        # No browser launch, driver connection, or profile/site-data access.
        release = load_release(config)
        return {"schemaVersion": 1, "code": "OK", "capabilities": CAPABILITIES, "release": config.release,
                "profileBusy": busy, "platform": release.metadata["platform"],
                "appVersion": release.metadata["appVersion"],
                "browserVersion": release.metadata["browserVersion"],
                "blockerVersion": release.metadata["blockerVersion"],
                "validation": release.metadata["validation"],
                "blockerConfigured": (config.data_dir / "state/blocker.json").is_file()}
    finally:
        lock.close()


async def run(config):
    reader = asyncio.StreamReader(limit=MAX_LINE + 1)
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    active = None
    owner = asyncio.current_task()

    def interrupt():
        if active and not active.done():
            active.cancel()
        else:
            owner.cancel()

    loop.add_signal_handler(signal.SIGINT, interrupt)
    loop.add_signal_handler(signal.SIGTERM, owner.cancel)
    try:
        async with BrowserSession(config) as session:
            while True:
                try:
                    line = await reader.readline()
                except ValueError:
                    emit(Result(None, status="error", code="INVALID_REQUEST").to_dict())
                    return 2
                if not line:
                    return 0
                if len(line.rstrip(b"\r\n")) > MAX_LINE:
                    emit(Result(None, status="error", code="INVALID_REQUEST").to_dict())
                    return 2
                try:
                    request = Request.parse(json.loads(line.decode("utf-8")))
                except (ValueError, UnicodeError, StealthishError):
                    emit(Result(None, status="error", code="INVALID_REQUEST").to_dict())
                    return 2
                active = asyncio.create_task(session.execute(request))
                try:
                    result = await active
                except asyncio.CancelledError:
                    result = Result(request.id, status="cancelled", code="CANCELLED",
                                    effect="unknown", warnings=["The action was not retried."])
                finally:
                    active = None
                emit(result.to_dict())
                if request.operation == "close":
                    return 0
    finally:
        transport.close()
        loop.remove_signal_handler(signal.SIGINT)
        loop.remove_signal_handler(signal.SIGTERM)


def selected_environment(config, argv):
    """A CLI caller follows the selected release; Python API callers select their own env."""
    root = child(config.data_dir / "releases", config.release)
    environment = root / "env"
    if environment.is_dir() and Path(sys.prefix).resolve() != environment.resolve():
        manifest = json.loads((root / "manifest.json").read_text())
        verify_files(child(root, manifest["environmentPath"]), manifest["environmentFiles"], ignore_bytecode=True)
        python = environment / "bin/python"
        os.execv(python, [str(python), "-I", "-B", "-m", "stealthish", *argv])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="stealthish", description="Standalone headless browser. Manual updates.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "status", "prepare", "activate", "recover", "_verify"):
        item = sub.add_parser(name)
        item.add_argument("--data-dir", type=Path)
        if name in ("run", "status"):
            item.add_argument("--config", type=Path)
        if name == "run":
            item.add_argument("--headed", action="store_true", help="Explicit human access; automation is blocked.")
            item.add_argument("--tab-policy", choices=("strict", "lru"))
        if name in ("prepare", "activate", "_verify"):
            item.add_argument("--release", required=True)
        if name == "recover":
            item.add_argument("--accept-data-loss", action="store_true")
        if name == "_verify":
            item.add_argument("--owner-fd", type=int, required=True)
            item.add_argument("--initialize", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command not in ("run", "status"):
            from . import maintenance
            root = (args.data_dir or default_paths()[1]).expanduser().resolve()
            if args.command == "_verify":
                asyncio.run(maintenance.verify_child(root, args.release, args.owner_fd, args.initialize))
                return 0
            if args.command == "prepare":
                result = maintenance.prepare(root, args.release)
            elif args.command == "activate":
                result = maintenance.activate(root, args.release)
            else:
                result = maintenance.recover(root, accept_data_loss=args.accept_data_loss)
            emit(result)
            return 0
        config = SessionConfig.load(args.config, data_dir=args.data_dir)
        selected_environment(config, argv)
        if args.command == "status":
            emit(status(config))
            return 0
        config = replace(config, headless=not args.headed,
                         tab_policy=args.tab_policy or config.tab_policy)
        return asyncio.run(run(config))
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 130
    except StealthishError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("STARTUP_ERROR: Startup failed. Details and inputs are omitted.", file=sys.stderr)
        return 2
