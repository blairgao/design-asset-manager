"""Image probing and derived files. EXIF is read from the original and stripped from derived."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image, ImageOps
from PIL.ExifTags import GPSTAGS, TAGS

try:  # HEIC/HEIF support is optional at import time so tests run without libheif.
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

THUMB_PX = 256
PREVIEW_PX = 1600
WEBP_QUALITY = 82

Image.MAX_IMAGE_PIXELS = 400_000_000


@dataclass
class Probe:
    width: int
    height: int
    captured_at: datetime | None = None
    exif: dict = field(default_factory=dict)
    has_gps: bool = False


def _parse_exif_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def probe(data: bytes) -> Probe:
    with Image.open(io.BytesIO(data)) as img:
        transposed = ImageOps.exif_transpose(img) or img
        width, height = transposed.size
        raw = img.getexif()
        exif: dict = {}
        captured_at = None
        has_gps = False
        for tag_id, value in raw.items():
            name = TAGS.get(tag_id, str(tag_id))
            if name == "GPSInfo":
                has_gps = True
                gps = raw.get_ifd(0x8825)
                exif["GPSInfo"] = {GPSTAGS.get(k, str(k)): _jsonable(v) for k, v in gps.items()}
                continue
            if isinstance(value, bytes) or name in ("MakerNote", "UserComment"):
                continue
            exif[name] = _jsonable(value)
        ifd = raw.get_ifd(0x8769)
        for tag_id, value in ifd.items():
            name = TAGS.get(tag_id, str(tag_id))
            if name in ("DateTimeOriginal", "DateTimeDigitized") and captured_at is None:
                captured_at = _parse_exif_dt(str(value))
            elif name not in ("MakerNote", "UserComment") and not isinstance(value, bytes):
                exif[name] = _jsonable(value)
        if captured_at is None and "DateTime" in exif:
            captured_at = _parse_exif_dt(str(exif["DateTime"]))
    return Probe(width=width, height=height, captured_at=captured_at, exif=exif, has_gps=has_gps)


def _jsonable(v):
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    if isinstance(v, (tuple, list)):
        return [_jsonable(x) for x in v]
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def derive(data: bytes) -> dict[str, tuple[bytes, int, int]]:
    """Return {variant: (webp_bytes, width, height)} for thumb and preview, EXIF stripped."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img) or img
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        out: dict[str, tuple[bytes, int, int]] = {}
        for variant, px in (("preview", PREVIEW_PX), ("thumb", THUMB_PX)):
            copy = img.copy()
            copy.thumbnail((px, px), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            # No exif= argument: derived files never carry camera or GPS metadata.
            copy.save(buf, format="WEBP", quality=WEBP_QUALITY, method=4)
            out[variant] = (buf.getvalue(), copy.width, copy.height)
    return out


def to_webp(data: bytes, max_px: int = PREVIEW_PX) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img) or img
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=4)
        return buf.getvalue()
