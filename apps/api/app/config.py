from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (works in a source checkout and inside the container image,
# where /app/apps/api/app/config.py -> /app).
ROOT_DIR = Path(__file__).resolve().parents[3]


def _env_path(name: str, default: Path) -> Path:
    """Resolve a possibly-relative path from env into an absolute Path.

    Relative values are resolved against the current working directory so that
    ``DISTILL_DATA_DIR=./data`` behaves the same on every platform and inside a
    container with a mounted volume.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


class Settings(BaseSettings):
    app_name: str = "蒸馏平台"
    api_prefix: str = "/api/v1"
    env: str = "development"

    # Storage. Defaults keep the local-first behaviour; a container deployment
    # overrides both with a mounted volume.
    data_dir: Path = _env_path("DISTILL_DATA_DIR", ROOT_DIR / "data")
    export_dir: Path = _env_path("DISTILL_EXPORT_DIR", ROOT_DIR / "exports")
    database_url: str = ""
    web_dist: Path = _env_path("DISTILL_WEB_DIST", ROOT_DIR / "apps" / "web" / "dist")

    # Runtime
    inline_worker: bool = True
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 300
    worker_id: str = ""
    max_concurrent_jobs: int = 1

    # Limits
    max_upload_mb: int = 256
    max_zip_entries: int = 500
    max_zip_uncompressed_mb: int = 1024
    chunk_chars: int = 800
    chunk_overlap: int = 120
    max_chunks_per_job: int = 240
    http_timeout_seconds: float = 90.0
    llm_max_retries: int = 3

    # Embeddings / ASR
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    embedding_backend: str = "auto"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_model_path: str = ""
    embedding_dim: int = 512
    embedding_batch_size: int = 32
    vector_search_limit: int = 8

    # HTTP
    cors_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    log_level: str = "INFO"
    log_json: bool = False

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_prefix="DISTILL_",
        extra="ignore",
    )

    def model_post_init(self, _context: object) -> None:  # noqa: D401
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"
        if not self.worker_id:
            import socket

            self.worker_id = f"{socket.gethostname()}-{os.getpid()}"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def skills_dir(self) -> Path:
        return self.data_dir / "skills"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / ".secret.key"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.sources_dir,
            self.artifacts_dir,
            self.skills_dir,
            self.export_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()