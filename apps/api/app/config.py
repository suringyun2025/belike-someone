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

    # --- Concurrency control (strict queueing) ----------------------------
    # Hard cap on simultaneously running jobs. Each distillation job holds
    # parsed text plus (optionally) an ONNX embedding model in memory, so this
    # must reflect real RAM, not CPU count. Default 1 is safe on a 1-2 GB host.
    max_concurrent_jobs: int = 1
    # Per-account cap, so one user cannot occupy every slot.
    max_jobs_per_user: int = 1
    # Refuse to start a job when available memory drops below this floor (MiB).
    # Set to 0 to disable the check.
    min_free_mb: int = 320
    # Above this many waiting jobs the API returns 429 instead of accepting more.
    # A short queue is honest; an hour-long one is a lie about availability.
    max_queue_length: int = 30
    # Reject uploads that would push a user past this total (enforced in the
    # upload handler alongside max_storage_mb_per_user).
    enforce_storage_quota: bool = True

    # --- Multi-user / public deployment -----------------------------------
    # When True every business endpoint requires a logged-in user and data is
    # scoped by owner_id. The single-user local build leaves this off so the
    # existing workflow keeps working without a login step.
    multiuser: bool = False
    allow_registration: bool = False
    session_days: int = 14
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    cookie_domain: str = ""
    # Bootstrap admin created on first start when multiuser is on and no user
    # exists. Leave the password empty to have one generated and logged once.
    admin_email: str = "admin@localhost"
    admin_password: str = ""
    # Fernet key or passphrase for sealing provider credentials. Must be stable:
    # rotating it makes every stored API key undecryptable.
    secret_key: str = ""

    # Abuse limits (applied per user and per IP).
    max_login_attempts: int = 8
    login_window_seconds: int = 300
    rate_limit_per_minute: int = 120
    max_projects_per_user: int = 20
    max_jobs_per_user: int = 2
    max_storage_mb_per_user: int = 2048

    # --- Public demo sandbox -----------------------------------------------
    # The public instance runs one visitor at a time: they bring their own model
    # endpoint, use the seat, and everything they create is deleted on exit.
    # This is a different product from the multiuser build, not a mode of it.
    sandbox: bool = False
    # Hard cap on a single turn. Long enough to run a real distillation and read
    # the result; short enough that the queue behind them moves.
    sandbox_visit_minutes: int = 30
    # Idle cutoff: a tab left open without requests stops holding the seat.
    sandbox_idle_minutes: int = 10
    # Public deployments should refuse plain http endpoints for the model API.
    sandbox_https_only: bool = True
    # Escape hatch for local development: lets the entry form point at a mock
    # endpoint on 127.0.0.1. Never enable this on a public instance — it is the
    # SSRF guard's off switch.
    sandbox_allow_private: bool = False
    sandbox_max_projects: int = 3
    sandbox_max_storage_mb: int = 256
    # A visitor may start this many jobs per turn; the worker still runs one at
    # a time, so this is a patience limit, not a parallelism one.
    sandbox_max_jobs: int = 12

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
        # Sandbox is a tenancy mode, not a separate auth path: visitors own their
        # own workspace, so every ownership check must stay on. Folding it into
        # ``multiuser`` here means the ~20 call sites that guard on that flag do
        # not each need a second condition to forget.
        if self.sandbox and not self.multiuser:
            self.multiuser = True
        # Registration is meaningless in a sandbox: identity comes from the seat,
        # not from an account someone creates.
        if self.sandbox:
            self.allow_registration = False

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