from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Every external dependency has a local mode so the
    whole pipeline runs on a laptop with nothing but Postgres."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_role: Literal["api", "worker", "all"] = "all"
    environment: str = "local"
    public_base_url: str = "http://localhost:8080"
    allowed_origins: str = "*"

    # Database. Either a plain DSN (local) or a Cloud SQL instance connection name (prod).
    database_url: str = "postgresql+asyncpg://tradecheck:tradecheck@localhost:5432/tradecheck"
    cloud_sql_instance: str | None = None
    db_user: str = "tradecheck"
    db_password: str | None = None
    db_name: str = "tradecheck"

    # Modes
    auth_mode: Literal["firebase", "dev"] = "dev"
    ai_mode: Literal["http", "stub"] = "stub"
    tasks_mode: Literal["cloudtasks", "inline", "sync"] = "inline"
    storage_mode: Literal["gcs", "local"] = "local"
    signing_mode: Literal["kms", "local"] = "local"

    # GCP
    gcp_project: str | None = None
    gcp_region: str = "asia-southeast1"
    gcs_bucket: str | None = None
    tasks_queue: str = "pipeline"
    worker_url: str | None = None
    tasks_service_account: str | None = None
    kms_key_version: str | None = None
    firebase_project: str | None = None

    # AI service
    ai_service_url: str | None = None
    ai_timeout_seconds: float = 120.0
    ai_stub_fixtures_dir: str = "../contracts/fixtures/ai"

    # Local fallbacks
    local_storage_dir: str = ".local/storage"
    local_signing_key: str = ".local/signing_key.pem"
    local_url_secret: str = "dev-only-secret-change-me"

    # Pipeline knobs (§11, §12.4, §13.4)
    render_dpi: int = 200
    render_max_px: int = 2048
    max_file_bytes: int = 50 * 1024 * 1024
    max_files_per_shipment: int = 20
    max_pages_per_document: int = 100
    max_pages_per_extract: int = 15
    confidence_floor: float = 0.55
    extract_concurrency: int = 4
    explain_cap: int = 10
    min_documents_with_fields: int = 1
    upload_url_ttl_seconds: int = 15 * 60
    read_url_ttl_seconds: int = 5 * 60

    # Cost table, USD per 1M tokens, for model_invocations.cost_usd
    price_input_per_m: float = 0.75
    price_output_per_m: float = 3.75

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
