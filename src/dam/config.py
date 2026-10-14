from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DAM_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "staging", "prod"] = "dev"
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

    # No sign-in yet: every request runs as this user, an admin of this firm.
    # Both are created on first request if missing.
    local_user_email: str = "local@example.com"
    local_user_name: str = "Local User"
    local_firm_slug: str = "local"
    local_firm_name: str = "My Studio"


@lru_cache
def get_settings() -> Settings:
    return Settings()
