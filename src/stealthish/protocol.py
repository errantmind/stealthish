"""Versioned requests and results. Request representations omit text values."""
from dataclasses import dataclass, field
import json
from typing import Any
from urllib.parse import urlsplit

from .errors import StealthishError

MAX_LINE = 1024 * 1024
SCHEMA = {
    "navigate": {"action", "url", "tabId", "tabPolicy", "waitUntil", "timeoutMs"},
    "snapshot": {"tabId", "maxChars", "saveArtifact", "saveOnTruncation", "boxes"},
    "interact": {"action", "tabId", "ref", "selector", "text", "key", "x", "y", "waitAfterMs"},
    "extract": {"tabId", "maxChars", "saveArtifact", "saveOnTruncation", "includeHtml"},
    "screenshot": {"tabId", "fullPage"},
    "tabs": {"action", "tabId", "url", "waitUntil", "timeoutMs"},
    "session_status": set(), "close": set(), "manual_open": {"url"},
    "resume": {"tabId", "confirmed"}, "restart": {"acknowledgeStateLoss"},
    "search": {"query", "engine", "tabId", "tabPolicy", "maxChars", "timeoutMs", "saveOnTruncation"},
}


CAPABILITIES = {"piAdapter": 1, "manualMode": True, "boxes": True,
                "tabPolicy": ["strict", "lru"], "searchEngines": [
                    "kagi", "google", "bing", "yahoo", "duckduckgo", "brave"]}


def http_url(value: Any) -> str:
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise StealthishError("INVALID_REQUEST")
    try:
        url = urlsplit(value)
        _ = url.port
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError()
    except ValueError:
        raise StealthishError("INVALID_REQUEST") from None
    return value


@dataclass(frozen=True)
class Request:
    id: str
    operation: str
    params: dict = field(default_factory=dict, repr=False)
    schemaVersion: int = 1

    def __post_init__(self):
        if type(self.schemaVersion) is not int or self.schemaVersion != 1:
            raise StealthishError("INVALID_REQUEST")
        if not isinstance(self.id, str) or not 1 <= len(self.id) <= 128:
            raise StealthishError("INVALID_REQUEST")
        if not isinstance(self.operation, str) or self.operation not in SCHEMA or not isinstance(self.params, dict):
            raise StealthishError("INVALID_REQUEST")
        if set(self.params) - SCHEMA[self.operation]:
            raise StealthishError("INVALID_REQUEST")
        try:
            if len(json.dumps(self.to_dict(), allow_nan=False).encode()) > MAX_LINE:
                raise ValueError()
        except (TypeError, ValueError):
            raise StealthishError("INVALID_REQUEST") from None

    def to_dict(self):
        return {"schemaVersion": self.schemaVersion, "id": self.id,
                "operation": self.operation, "params": self.params}

    @classmethod
    def parse(cls, value):
        try:
            if not isinstance(value, dict) or set(value) != {"schemaVersion", "id", "operation", "params"}:
                raise ValueError()
            return cls(**value)
        except (TypeError, ValueError):
            raise StealthishError("INVALID_REQUEST") from None


@dataclass
class Result:
    id: str | None
    status: str = "ok"
    code: str = "OK"
    effect: str = "none"
    data: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    truncation: dict = field(default_factory=lambda: {"truncated": False})
    schemaVersion: int = 1

    def to_dict(self):
        return vars(self).copy()
