from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEV_SECRET = "dev-only-insecure-secret-key-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DAM_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    # Insecure default so imports and tests work without a .env; refused outside dev/test.
    secret_key: str = Field(default=INSECURE_DEV_SECRET, min_length=16)
    base_url: str = "http://localhost:8000"
    web_origin: str = "http://localhost:5173"

    database_url: str = "postgresql+asyncpg://dam:dam@localhost:5432/dam"
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (ADR-013)
    s3_bucket: str = "dam-dev"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None
    cloudfront_domain: str | None = None
    cloudfront_key_id: str | None = None
    cloudfront_private_key_path: str | None = None
    presign_ttl_seconds: int = 15 * 60
    multipart_part_size: int = 64 * 1024 * 1024

    # Limits (DESIGN.md section 6)
    max_image_bytes: int = 200 * 1024 * 1024
    max_video_bytes: int = 10 * 1024 * 1024 * 1024

    # Models
    vision_model: str = "claude-opus-5-5"
    vision_effort: Literal["low", "medium", "high"] = "low"
    embedding_provider: Literal["voyage", "fake"] = "voyage"
    embedding_model: str = "voyage-multimodal-3"
    embedding_dim: int = 1024
    monthly_enrichment_budget_tokens: int = 50_000_000

    # Video (ADR-008)
    video_keyframe_min_interval_s: float = 5.0
    video_keyframe_max: int = 60
    video_scene_threshold: float = 0.3

    # Auth (ADR-011)
    magic_link_ttl_seconds: int = 15 * 60
    session_ttl_seconds: int = 30 * 24 * 3600

    # Mail
    mail_backend: Literal["console", "smtp"] = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    mail_from: str = "no-reply@example.com"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.env in ("staging", "prod") and settings.secret_key == INSECURE_DEV_SECRET:
        raise RuntimeError("DAM_SECRET_KEY must be set outside dev")
    return settings
