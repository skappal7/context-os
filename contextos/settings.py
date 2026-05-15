from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir, user_log_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_APP = "contextos"
_VENDOR = "DataDojo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTEXTOS_", env_file=".env", extra="ignore")

    proxy_host: str = "127.0.0.1"
    proxy_port: int = 9137
    dashboard_port: int = 9138

    anthropic_upstream: str = "https://api.anthropic.com"
    openai_upstream: str = "https://api.openai.com"

    # Local generator (llama-cpp + GGUF). SmolLM2-360M is small enough to stay within
    # PRD §8 memory budgets while still following multi-rule instruction prompts.
    llm_repo_id: str = "bartowski/Qwen2.5-0.5B-Instruct-GGUF"
    llm_filename: str = "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
    llm_n_ctx: int = 4096
    llm_max_tokens: int = 200

    # Local embedder (fastembed + ONNX). bge-small-en-v1.5 = 384-dim sentence vectors.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    retrieval_top_k: int = 3

    request_timeout_s: float = 600.0
    connect_timeout_s: float = 10.0

    data_dir: Path = Field(default_factory=lambda: Path(user_data_dir(_APP, _VENDOR)))
    log_dir: Path = Field(default_factory=lambda: Path(user_log_dir(_APP, _VENDOR)))

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ledger.duckdb"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def pid_file(self) -> Path:
        return self.data_dir / "daemon.pid"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.log_dir, self.backup_dir, self.model_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def configure_logging(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    logging.basicConfig(
        level=s.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(s.log_dir / "contextos.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
