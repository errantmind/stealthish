"""Explicit private artifacts. No filenames or paths are taken from page content."""
import os
import secrets

from .errors import StealthishError
from .ownership import private_directory


def requested(params, name):
    value = params.get(name, False)
    if type(value) is not bool:
        raise StealthishError("INVALID_REQUEST")
    return value


def save_text(config, text, suffix):
    if suffix not in {"txt", "html"}:
        raise ValueError("Unsupported artifact type")
    root = config.data_dir / "artifacts"
    private_directory(root)
    path = root / (secrets.token_hex(16) + "." + suffix)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            output.write(text)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": str(path), "format": suffix, "characters": len(text),
            "bytes": path.stat().st_size}
