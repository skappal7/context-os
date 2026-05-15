from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from contextos.installer.detector import IDETarget, detect, known_targets
from contextos.settings import Settings, get_settings

log = logging.getLogger("contextos.installer")

# Per-IDE config keys for the API base URL override. Centralized so the patch surface
# is auditable; each IDE schema is documented inline.
_BASE_URL_KEYS: dict[str, tuple[str, ...]] = {
    "claude-code": ("env", "ANTHROPIC_BASE_URL"),
    "cursor": ("anthropic", "baseURL"),
    "codex": ("provider", "base_url"),
    "continue": ("models", "apiBase"),
    "aider": ("openai-api-base",),
}


def _load(target: IDETarget) -> Any:
    text = target.config_path.read_text(encoding="utf-8")
    if target.format == "json":
        return json.loads(text) if text.strip() else {}
    return yaml.safe_load(text) or {}


def _dump(target: IDETarget, data: Any) -> str:
    if target.format == "json":
        return json.dumps(data, indent=2)
    return yaml.safe_dump(data, sort_keys=False)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as f:
        f.write(text)
        tmp = Path(f.name)
    tmp.replace(path)


def _set_nested(data: dict[str, Any], keys: tuple[str, ...], value: str) -> None:
    cur: dict[str, Any] = data
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _backup(target: IDETarget, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_dir / f"{target.name}.{stamp}{target.config_path.suffix}"
    shutil.copy2(target.config_path, dest)
    # Also keep a "latest" pointer for easy restore.
    latest = backup_dir / f"{target.name}.latest{target.config_path.suffix}"
    shutil.copy2(target.config_path, latest)
    return dest


def install_all(settings: Settings | None = None) -> list[IDETarget]:
    s = settings or get_settings()
    base_url = f"http://{s.proxy_host}:{s.proxy_port}"
    patched: list[IDETarget] = []
    for target in detect():
        try:
            _backup(target, s.backup_dir)
            data = _load(target)
            if not isinstance(data, dict):
                log.warning("skip %s: unexpected config root type", target.name)
                continue
            _set_nested(data, _BASE_URL_KEYS[target.name], base_url)
            _atomic_write(target.config_path, _dump(target, data))
            patched.append(target)
            log.info("patched %s -> %s", target.name, base_url)
        except Exception as e:
            log.error("failed to patch %s: %s", target.name, e)
    return patched


def uninstall_all(settings: Settings | None = None) -> list[IDETarget]:
    s = settings or get_settings()
    restored: list[IDETarget] = []
    for target in known_targets():
        latest = s.backup_dir / f"{target.name}.latest{target.config_path.suffix}"
        if not latest.exists():
            continue
        try:
            shutil.copy2(latest, target.config_path)
            restored.append(target)
            log.info("restored %s", target.name)
        except Exception as e:
            log.error("failed to restore %s: %s", target.name, e)
    return restored
