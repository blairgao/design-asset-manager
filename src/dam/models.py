"""SQLAlchemy models. See DESIGN.md section 5 for the shape and rationale."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from dam.config import get_settings


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    type_annotation_map = {uuid.UUID: UUID(as_uuid=True), dict: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FirmRole(enum.StrEnum):
    admin = "admin"
    staff = "staff"
    client = "client"


class ProjectRole(enum.StrEnum):
    editor = "editor"
    viewer = "viewer"


class AssetKind(enum.StrEnum):
    image = "image"
    video = "video"


class AssetStatus(enum.StrEnum):
    uploading = "uploading"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class TagSource(enum.StrEnum):
    auto = "auto"
    manual = "manual"


class Firm(TimestampMixin, Base):
    __tablename__ = "firm"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    plan: Mapped[str] = mapped_column(String(40), default="standard")
    enrichment_budget_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class User(TimestampMixin, Base):
    __tablename__ = "user"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)



class Membership(TimestampMixin, Base):
    __tablename__ = "membership"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[FirmRole] = mapped_column(Enum(FirmRole, name="firm_role"))


class Project(TimestampMixin, Base):
    __tablename__ = "project"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    client_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")


class ProjectAccess(TimestampMixin, Base):
    __tablename__ = "project_access"
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[ProjectRole] = mapped_column(Enum(ProjectRole, name="project_role"))


class Asset(TimestampMixin, Base):
    __tablename__ = "asset"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    uploader_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[AssetKind] = mapped_column(Enum(AssetKind, name="asset_kind"))
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"), default=AssetStatus.uploading
    )
    filename: Mapped[str] = mapped_column(String(512))
    storage_key: Mapped[str] = mapped_column(String(1024))
    mime: Mapped[str] = mapped_column(String(120))
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    internal_only: Mapped[bool] = mapped_column(Boolean, default=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exif: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    upload_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    derived: Mapped[list[AssetDerived]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    tags: Mapped[list[AssetTag]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    text: Mapped[AssetText | None] = relationship(
        cascade="all, delete-orphan", lazy="selectin", uselist=False
    )

    __table_args__ = (
        Index("ix_asset_firm_project_created", "firm_id", "project_id", "created_at"),
        Index("ix_asset_firm_sha", "firm_id", "sha256"),
    )


class AssetDerived(Base):
    __tablename__ = "asset_derived"
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True)
    variant: Mapped[str] = mapped_column(String(40), primary_key=True)  # thumb|preview|poster|keyframe_3
    storage_key: Mapped[str] = mapped_column(String(1024))
    mime: Mapped[str] = mapped_column(String(120))
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp_s: Mapped[float | None] = mapped_column(Float, nullable=True)


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("firm.id", ondelete="CASCADE"), nullable=True
    )
    namespace: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(120))
    __table_args__ = (
        Index("uq_tag_global", "namespace", "value", unique=True, postgresql_where="firm_id IS NULL"),
        Index(
            "uq_tag_firm",
            "firm_id",
            "namespace",
            "value",
            unique=True,
            postgresql_where="firm_id IS NOT NULL",
        ),
    )


class AssetTag(TimestampMixin, Base):
    __tablename__ = "asset_tag"
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"))
    source: Mapped[TagSource] = mapped_column(Enum(TagSource, name="tag_source"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # A manual row with suppressed=True means "a human removed this; never auto-add it again".
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    tag: Mapped[Tag] = relationship(lazy="joined")
    __table_args__ = (Index("ix_asset_tag_firm_tag", "firm_id", "tag_id"),)


class AssetText(Base):
    __tablename__ = "asset_text"
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    colors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    objects: Mapped[list | None] = mapped_column(JSON, nullable=True)
    keyframes: Mapped[list | None] = mapped_column(JSON, nullable=True)  # per-keyframe results
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


def _dim() -> int:
    return get_settings().embedding_dim


class AssetEmbedding(TimestampMixin, Base):
    """One row per (asset, model, frame). frame=-1 is the asset-level vector."""

    __tablename__ = "asset_embedding"
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(120), primary_key=True)
    frame: Mapped[int] = mapped_column(Integer, primary_key=True, default=-1)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    timestamp_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    vector: Mapped[list[float]] = mapped_column(Vector(_dim()))
    __table_args__ = (
        Index("ix_asset_embedding_firm_project", "firm_id", "project_id"),
        Index(
            "ix_asset_embedding_hnsw",
            "vector",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"vector": "vector_cosine_ops"},
        ),
    )


class Board(TimestampMixin, Base):
    __tablename__ = "board"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    shared_with_clients: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    __table_args__ = (Index("ix_board_firm_project", "firm_id", "project_id"),)


class BoardAsset(Base):
    __tablename__ = "board_asset"
    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("board.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class Comment(TimestampMixin, Base):
    __tablename__ = "comment"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text)


class Favorite(TimestampMixin, Base):
    __tablename__ = "favorite"
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class EnrichmentUsage(Base):
    """Per-firm monthly model token usage for budgets (DESIGN.md section 11)."""

    __tablename__ = "enrichment_usage"
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firm.id", ondelete="CASCADE"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    assets_enriched: Mapped[int] = mapped_column(Integer, default=0)

