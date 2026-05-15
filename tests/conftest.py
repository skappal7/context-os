from __future__ import annotations

from pathlib import Path

import pytest

from contextos.settings import Settings, get_settings


@pytest.fixture
def tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CONTEXTOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CONTEXTOS_LOG_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    s = get_settings()
    return s
