from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IDETarget:
    name: str
    config_path: Path
    format: str  # "json" or "yaml"


def _home() -> Path:
    return Path.home()


def known_targets() -> list[IDETarget]:
    h = _home()
    return [
        IDETarget("claude-code", h / ".claude" / "settings.json", "json"),
        IDETarget("cursor", h / ".cursor" / "settings.json", "json"),
        IDETarget("codex", h / ".codex" / "config.json", "json"),
        IDETarget("continue", h / ".continue" / "config.json", "json"),
        IDETarget("aider", h / ".aider.conf.yml", "yaml"),
    ]


def detect() -> list[IDETarget]:
    return [t for t in known_targets() if t.config_path.exists()]
