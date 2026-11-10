"""Small, strict configuration shared by the CLI and Python API."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import tomllib

from .errors import StartupError

RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


def default_paths() -> tuple[Path, Path]:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Stealthish"
        return base / "config.toml", base
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "stealthish"
    return base / "config.toml", base


@dataclass(frozen=True)
class SessionConfig:
    data_dir: Path
    release: str
    action_timeout: float = 120
    navigation_timeout: float = 60
    text_limit: int = 16000
    tab_limit: int = 20
    rendering: str = "linux-vulkan"
    search_engine: str = "kagi"
    headless: bool = True
    tab_policy: str = "strict"

    def __post_init__(self):
        try:
            path = Path(self.data_dir).expanduser().resolve()
            if not path.is_absolute() or not RELEASE_ID.fullmatch(self.release):
                raise ValueError()
            for value in (self.action_timeout, self.navigation_timeout):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 600:
                    raise ValueError()
            if type(self.text_limit) is not int or not 1 <= self.text_limit <= 100000:
                raise ValueError()
            if type(self.tab_limit) is not int or not 1 <= self.tab_limit <= 20:
                raise ValueError()
            if self.rendering != "linux-vulkan" or self.search_engine not in {
                "kagi", "google", "bing", "yahoo", "duckduckgo", "brave"
            }:
                raise ValueError()
            if type(self.headless) is not bool or self.tab_policy not in {"strict", "lru"}:
                raise ValueError()
            object.__setattr__(self, "data_dir", path)
        except (TypeError, ValueError, OSError):
            raise StartupError("INVALID_CONFIG") from None

    @classmethod
    def load(cls, path: Path | None = None, *, data_dir: Path | None = None):
        config_path, default_data = default_paths()
        if data_dir is not None and path is None:
            config_path = Path(data_dir).expanduser() / "config.toml"
        try:
            document = tomllib.loads((path or config_path).read_text(encoding="utf-8"))
            allowed = {"schema_version", "release", "data_dir", "action_timeout",
                       "navigation_timeout", "text_limit", "tab_limit", "rendering", "search_engine",
                       "headless", "tab_policy"}
            if set(document) - allowed or type(document.get("schema_version")) is not int:
                raise ValueError()
            if document.pop("schema_version") != 1:
                raise ValueError()
            document["data_dir"] = data_dir if data_dir is not None else document.get("data_dir", default_data)
            return cls(**document)
        except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError):
            raise StartupError("INVALID_CONFIG") from None
