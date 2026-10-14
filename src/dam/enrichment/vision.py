"""Claude vision call for captions, tags, OCR, and colors (ADR-005).

The request is shaped for prompt caching: the static system prompt and the firm's
vocabulary come first and carry a cache breakpoint; the per-asset context and images follow.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache

import anthropic
from pydantic import BaseModel, Field

from dam.config import get_settings

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
MAX_TAGS_PER_NAMESPACE = 6


class TagOut(BaseModel):
    namespace: str
    value: str
    confidence: float = Field(ge=0, le=1)


class Moment(BaseModel):
    frame_index: int
    caption: str


class VisionResult(BaseModel):
    caption: str
    tags: list[TagOut] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    ocr_text: str = ""
    colors: list[str] = Field(default_factory=list)
    people_present: bool = False
    moments: list[Moment] = Field(default_factory=list)


@dataclass
class VisionUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    model: str = ""
    served_by: str = ""
    prompt_hash: str = ""
    extra: dict = field(default_factory=dict)


SYSTEM_PROMPT = """You catalog visual assets for an architecture and interior design firm.

For each image (or set of keyframes from one video) produce a JSON object that helps designers
find the asset later. Rules:

- caption: one or two sentences a designer would write. Name the space, the dominant materials
  and finishes, the light, and the mood. Do not start with "This image shows".
- tags: choose only from the vocabulary below for the room, phase, style and material
  namespaces; use the exact strings. Prefer fewer, confident tags over many weak ones. Omit a
  namespace entirely when nothing fits. Give a confidence from 0 to 1.
- objects: notable furniture, fixtures, fittings or elements, lowercase, singular, generic
  ("pendant light", "island", "built-in shelving"). Up to 12.
- ocr_text: any legible text in the image (labels, signage, drawing titles, sample codes),
  verbatim. Empty string if none.
- colors: up to 5 dominant colors as lowercase hex, most dominant first.
- people_present: true if any person is visible. Never describe, identify or guess anything
  about people; they are not the subject of the catalog.
- phase: infer from context. Raw site photos and demolition are "existing conditions" or
  "construction"; renders and sketches are "concept" or "schematic design"; mood boards and
  magazine-like references are "inspiration"; finished photography is "completed".
- For a video, also return moments: one short caption per keyframe index where the scene
  meaningfully changes, so a search can jump to that point. Leave moments empty for a single
  image.

Return only the JSON object."""


def vocabulary_block(vocab: dict[str, list[str]]) -> str:
    closed = {ns: vocab.get(ns, []) for ns in ("room", "phase", "style", "material")}
    return "Vocabulary (closed namespaces):\n" + json.dumps(closed, sort_keys=True, indent=0)


def output_schema(vocab: dict[str, list[str]], *, video: bool) -> dict:
    """JSON schema with the closed namespaces enforced as enums."""
    closed = {ns: sorted(set(vocab.get(ns, []))) for ns in ("room", "phase", "style", "material")}
    tag_variants = [
        {
            "type": "object",
            "properties": {
                "namespace": {"const": ns},
                "value": {"type": "string", "enum": values or ["none"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["namespace", "value", "confidence"],
            "additionalProperties": False,
        }
        for ns, values in closed.items()
    ]
    schema: dict = {
        "type": "object",
        "properties": {
            "caption": {"type": "string"},
            "tags": {"type": "array", "items": {"anyOf": tag_variants}, "maxItems": 24},
            "objects": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
            "ocr_text": {"type": "string"},
            "colors": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            },
            "people_present": {"type": "boolean"},
            "moments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "frame_index": {"type": "integer", "minimum": 0},
                        "caption": {"type": "string"},
                    },
                    "required": ["frame_index", "caption"],
                    "additionalProperties": False,
                },
                "maxItems": 60 if video else 0,
            },
        },
        "required": [
            "caption",
            "tags",
            "objects",
            "ocr_text",
            "colors",
            "people_present",
            "moments",
        ],
        "additionalProperties": False,
    }
    return schema


def prompt_hash(vocab: dict[str, list[str]]) -> str:
    h = hashlib.sha256()
    h.update(PROMPT_VERSION.encode())
    h.update(SYSTEM_PROMPT.encode())
    h.update(vocabulary_block(vocab).encode())
    return h.hexdigest()[:16]


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=3, timeout=180.0)


def _image_block(data: bytes, media_type: str = "image/webp") -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode(),
        },
    }


def describe(
    images: list[bytes],
    *,
    vocab: dict[str, list[str]],
    project_name: str,
    project_phase: str | None,
    filename: str,
    video: bool = False,
    frame_timestamps: list[float] | None = None,
) -> tuple[VisionResult, VisionUsage]:
    """One request per asset. Keyframes of a video are sent together, in order."""
    settings = get_settings()
    context_lines = [f"Project: {project_name}"]
    if project_phase:
        context_lines.append(f"Project phase (hint, may be overridden by the image): {project_phase}")
    context_lines.append(f"Original filename: {filename}")
    if video:
        context_lines.append(f"This is a video; {len(images)} keyframes follow in order, index 0 first.")
        if frame_timestamps:
            ts = ", ".join(f"{i}: {t:.1f}s" for i, t in enumerate(frame_timestamps))
            context_lines.append(f"Keyframe timestamps: {ts}")

    content: list[dict] = [{"type": "text", "text": "\n".join(context_lines)}]
    for i, data in enumerate(images):
        if video:
            content.append({"type": "text", "text": f"Keyframe {i}:"})
        content.append(_image_block(data))

    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": vocabulary_block(vocab),
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]

    response = _client().beta.messages.create(
        model=settings.vision_model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={
            "effort": settings.vision_effort,
            "format": {"type": "json_schema", "schema": output_schema(vocab, video=video)},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    usage = VisionUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        model=settings.vision_model,
        served_by=response.model,
        prompt_hash=prompt_hash(vocab),
    )

    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        raise VisionRefused(f"model declined to describe asset (category={category})")
    if response.stop_reason == "max_tokens":
        raise VisionError("vision response truncated")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise VisionError("vision response had no text block")
    try:
        result = VisionResult.model_validate_json(text)
    except ValueError as e:
        raise VisionError(f"vision response was not valid JSON: {e}") from e

    # Belt and braces on top of the schema: cap per-namespace tags and drop the enum placeholder.
    counts: dict[str, int] = {}
    kept: list[TagOut] = []
    for tag in sorted(result.tags, key=lambda t: -t.confidence):
        if tag.value == "none":
            continue
        counts[tag.namespace] = counts.get(tag.namespace, 0) + 1
        if counts[tag.namespace] <= MAX_TAGS_PER_NAMESPACE:
            kept.append(tag)
    result.tags = kept
    return result, usage


class VisionError(RuntimeError):
    pass


class VisionRefused(VisionError):
    """Not retryable: the whole fallback chain declined."""
