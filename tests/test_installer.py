from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from contextos.installer import detector, patcher


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(detector, "_home", lambda: tmp_path)
    return tmp_path


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_detect_only_existing(fake_home: Path) -> None:
    _write_json(fake_home / ".claude" / "settings.json", {"existing": True})
    found = {t.name for t in detector.detect()}
    assert "claude-code" in found
    assert "cursor" not in found


def test_install_and_uninstall_roundtrip(fake_home: Path, tmp_settings) -> None:
    original = {"existing": True, "env": {"OTHER": "v"}}
    cfg = fake_home / ".claude" / "settings.json"
    _write_json(cfg, original)

    patched = patcher.install_all(tmp_settings)
    assert any(t.name == "claude-code" for t in patched)

    after = json.loads(cfg.read_text(encoding="utf-8"))
    assert after["env"]["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:")
    assert after["env"]["OTHER"] == "v"
    assert after["existing"] is True

    patcher.uninstall_all(tmp_settings)
    restored = json.loads(cfg.read_text(encoding="utf-8"))
    assert restored == original


def test_cursor_patch(fake_home: Path, tmp_settings) -> None:
    cfg = fake_home / ".cursor" / "settings.json"
    _write_json(cfg, {"editor.fontSize": 14})
    patcher.install_all(tmp_settings)
    after = json.loads(cfg.read_text(encoding="utf-8"))
    assert after["anthropic"]["baseURL"].startswith("http://127.0.0.1:")
    assert after["editor.fontSize"] == 14


def test_codex_patch(fake_home: Path, tmp_settings) -> None:
    cfg = fake_home / ".codex" / "config.json"
    _write_json(cfg, {"model": "gpt-4o"})
    patcher.install_all(tmp_settings)
    after = json.loads(cfg.read_text(encoding="utf-8"))
    assert after["provider"]["base_url"].startswith("http://127.0.0.1:")
    assert after["model"] == "gpt-4o"


def test_continue_patch(fake_home: Path, tmp_settings) -> None:
    cfg = fake_home / ".continue" / "config.json"
    _write_json(cfg, {"theme": "dark"})
    patcher.install_all(tmp_settings)
    after = json.loads(cfg.read_text(encoding="utf-8"))
    assert after["models"]["apiBase"].startswith("http://127.0.0.1:")
    assert after["theme"] == "dark"


def test_aider_yaml_patch(fake_home: Path, tmp_settings) -> None:
    cfg = fake_home / ".aider.conf.yml"
    cfg.write_text(yaml.safe_dump({"auto-commits": True}), encoding="utf-8")
    patcher.install_all(tmp_settings)
    after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert after["openai-api-base"].startswith("http://127.0.0.1:")
    assert after["auto-commits"] is True

    patcher.uninstall_all(tmp_settings)
    restored = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert restored == {"auto-commits": True}


def test_install_skips_missing(fake_home: Path, tmp_settings) -> None:
    # No configs present anywhere.
    patched = patcher.install_all(tmp_settings)
    assert patched == []
