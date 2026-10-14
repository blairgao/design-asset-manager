"""API request/response shapes. The OpenAPI document generated from these is the client contract."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from dam.models import AssetKind, AssetStatus, FirmRole, ProjectRole, TagSource


class Problem(BaseModel):
    """RFC 9457 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None


# --- me ----------------------------------------------------------------------


class MembershipOut(BaseModel):
    firm_id: uuid.UUID
    firm_name: str
    firm_slug: str
    role: FirmRole


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    memberships: list[MembershipOut]
    active_firm_id: uuid.UUID | None


# --- firms / projects --------------------------------------------------------


class FirmCreate(BaseModel):  # used by the admin CLI
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$")


class FirmOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    client_label: str | None = None
    phase: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    client_label: str | None = None
    phase: str | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    firm_id: uuid.UUID
    name: str
    client_label: str | None
    phase: str | None
    status: str
    created_at: datetime
    asset_count: int = 0


class ProjectInvite(BaseModel):
    email: EmailStr
    role: ProjectRole = ProjectRole.viewer


class ProjectAccessOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str | None
    role: ProjectRole


# --- uploads -----------------------------------------------------------------


class UploadStart(BaseModel):
    project_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=512)
    mime: str
    size: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class UploadSessionOut(BaseModel):
    asset_id: uuid.UUID
    upload_id: str | None
    part_size: int
    part_urls: list[str]
    deduplicated: bool = False


class UploadPart(BaseModel):
    part_number: int = Field(ge=1)
    etag: str


class UploadComplete(BaseModel):
    parts: list[UploadPart] = Field(default_factory=list)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


# --- assets ------------------------------------------------------------------


class TagOut(BaseModel):
    id: uuid.UUID
    namespace: str
    value: str
    source: TagSource
    confidence: float | None = None


class DerivedOut(BaseModel):
    variant: str
    url: str
    width: int | None
    height: int | None
    timestamp_s: float | None = None


class AssetOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: AssetKind
    status: AssetStatus
    filename: str
    mime: str
    bytes: int
    width: int | None
    height: int | None
    duration_s: float | None
    internal_only: bool
    captured_at: datetime | None
    created_at: datetime
    uploader_id: uuid.UUID | None
    caption: str | None = None
    ocr_text: str | None = None
    colors: list[str] | None = None
    tags: list[TagOut] = Field(default_factory=list)
    thumb_url: str | None = None
    preview_url: str | None = None
    derived: list[DerivedOut] = Field(default_factory=list)
    failure_reason: str | None = None
    favorited: bool = False


class AssetUpdate(BaseModel):
    caption: str | None = None
    internal_only: bool | None = None
    captured_at: datetime | None = None
    project_id: uuid.UUID | None = None


class AssetDownloadOut(BaseModel):
    url: str
    expires_in: int


class TagAdd(BaseModel):
    namespace: str = Field(pattern=r"^[a-z_]{2,40}$")
    value: str = Field(min_length=1, max_length=120)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


# --- search ------------------------------------------------------------------


class SearchFilters(BaseModel):
    project_id: list[uuid.UUID] | None = None
    kind: AssetKind | None = None
    room: list[str] | None = None
    phase: list[str] | None = None
    style: list[str] | None = None
    material: list[str] | None = None
    color: list[str] | None = None
    object: list[str] | None = None
    status: AssetStatus | None = None
    favorites_only: bool = False


class SearchRequest(BaseModel):
    q: str | None = Field(default=None, max_length=500)
    similar_to: uuid.UUID | None = None
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


class SearchHit(BaseModel):
    asset: AssetOut
    score: float
    matched_tags: list[str] = Field(default_factory=list)
    matched_timestamp_s: float | None = None


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    next_cursor: str | None = None
    mode: Literal["semantic", "similar", "browse"]


class FacetValue(BaseModel):
    value: str
    count: int


class FacetsResponse(BaseModel):
    facets: dict[str, list[FacetValue]]


# --- boards / comments -------------------------------------------------------


class BoardCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)


class BoardUpdate(BaseModel):
    name: str | None = None
    shared_with_clients: bool | None = None


class BoardOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    shared_with_clients: bool
    created_by: uuid.UUID | None
    created_at: datetime
    asset_count: int = 0
    cover_url: str | None = None


class BoardAssetsUpdate(BaseModel):
    asset_ids: list[uuid.UUID]


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    author_id: uuid.UUID | None
    author_name: str | None
    body: str
    created_at: datetime
