"""In-memory stand-in for the API so the web client can be developed without Postgres,
Redis, S3, or model keys.

    uv run python scripts/mock_api.py            # http://localhost:8000

Every route the client uses is implemented loosely: data lives in dicts, "uploads" complete
instantly, search is a substring match over captions and tags, and "find similar" returns
assets sharing a room tag. Images are generated gradients.
"""

from __future__ import annotations

import io
import json
import math
import random
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from shutil import which

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageOps

try:  # iPhone photos
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

MEDIA = Path(tempfile.mkdtemp(prefix="dam-mock-media-"))
BASE = "http://localhost:8000"
rng = random.Random(7)
now = datetime.now(UTC)

app = FastAPI(title="DAM mock API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag"],
)

# --- seed data ---------------------------------------------------------------

FIRM = {"id": str(uuid.uuid4()), "name": "Studio Arc", "slug": "studio-arc"}
USER = {"id": str(uuid.uuid4()), "email": "blair@studioarc.example", "name": "Blair Gao"}
CLIENT = {"id": str(uuid.uuid4()), "email": "owner@harborhouse.example", "name": None}

PROJECTS = {
    p["id"]: p
    for p in [
        {"id": str(uuid.uuid4()), "name": "Harbor House", "client_label": "Lindqvist family",
         "phase": "design development", "status": "active"},
        {"id": str(uuid.uuid4()), "name": "Mercer Street Lobby", "client_label": "Mercer Holdings",
         "phase": "construction", "status": "active"},
        {"id": str(uuid.uuid4()), "name": "Atelier Café", "client_label": "Rosa & Co.",
         "phase": "concept", "status": "active"},
    ]
}
for p in PROJECTS.values():
    p["firm_id"] = FIRM["id"]
    p["created_at"] = (now - timedelta(days=rng.randint(10, 200))).isoformat()

SCENES = [
    ("kitchen", "modern", ["white oak", "quartz", "brass"], ["island", "pendant light", "bar stool"],
     ["#e8dcc8", "#8a6a4a", "#2b2b2b"], "Bright kitchen with a white oak island, honed quartz counters and unlacquered brass fixtures under three linen pendants."),
    ("living room", "mid-century", ["walnut", "boucle", "terrazzo"], ["sofa", "coffee table", "floor lamp"],
     ["#d9cfc1", "#5a3e2b", "#c2b280"], "Sunken living room with a walnut credenza, cream boucle sofa and a terrazzo hearth catching late afternoon light."),
    ("bathroom", "minimalist", ["microcement", "travertine", "blackened steel"], ["freestanding tub", "wall sconce"],
     ["#cfc8bd", "#9a8f80", "#1f1f1f"], "Minimal bathroom in warm grey microcement with a travertine ledge and a blackened steel shower screen."),
    ("lobby", "contemporary", ["marble", "bronze", "velvet"], ["reception desk", "lounge chair", "planter"],
     ["#f1ece4", "#7d5a3c", "#3a4a3f"], "Double-height lobby with a book-matched marble reception desk, bronze reveals and forest green velvet seating."),
    ("bedroom", "scandinavian", ["ash", "linen", "wool"], ["bed", "nightstand", "rug"],
     ["#efe9df", "#b9a995", "#6d7b6a"], "Calm bedroom with an ash platform bed, washed linen and a chunky wool rug over wide plank floors."),
    ("facade", "brutalist", ["concrete", "glass", "steel"], ["canopy", "signage"],
     ["#9c9a94", "#5c5c5c", "#c9d2d8"], "Board-formed concrete facade with a cantilevered steel canopy and full-height glazing at the entry."),
    ("dining room", "japandi", ["oak", "plaster", "rattan"], ["dining table", "pendant light", "sideboard"],
     ["#e6dccd", "#a67c52", "#d8c7a6"], "Dining room with a long oak table, rattan chairs and a hand-troweled plaster wall under a paper pendant."),
    ("restaurant", "industrial", ["brick", "reclaimed wood", "stainless steel"], ["banquette", "bar", "open shelving"],
     ["#8b5e3c", "#3d3d3d", "#c7c7c7"], "Café interior with exposed brick, reclaimed wood banquettes and a stainless steel service bar."),
    ("site", "existing conditions", ["concrete", "drywall"], ["scaffold", "window opening"],
     ["#a8a39b", "#6f6b66", "#d6d2cb"], "Demolition in progress on level two: stripped partitions, exposed slab and new window openings framed."),
]
PHASES = ["inspiration", "concept", "design development", "construction", "completed"]

ASSETS: dict[str, dict] = {}
COMMENTS: dict[str, list[dict]] = {}
FAVORITES: set[str] = set()
BOARDS: dict[str, dict] = {}
BOARD_ASSETS: dict[str, list[str]] = {}


def _hex(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i: i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _render(asset_id: str, colors: list[str], label: str, w: int, h: int) -> dict[str, str]:
    c0, c1, c2 = (_hex(c) for c in colors[:3])
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            a, b = (c0, c1) if t < 0.5 else (c1, c2)
            u = t * 2 if t < 0.5 else (t - 0.5) * 2
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3))
    d = ImageDraw.Draw(img)
    # a few "architectural" shapes so thumbnails are not pure gradients
    for i in range(4):
        x0 = int(w * (0.1 + i * 0.22))
        d.rectangle([x0, int(h * 0.55), x0 + int(w * 0.14), int(h * 0.9)], outline=(255, 255, 255), width=3)
    d.text((24, 24), label, fill=(255, 255, 255))
    out = {}
    for variant, size in (("preview", 1600), ("thumb", 256)):
        copy = img.copy()
        copy.thumbnail((size, size))
        path = MEDIA / f"{asset_id}_{variant}.webp"
        copy.save(path, "WEBP", quality=80)
        out[variant] = f"{BASE}/media/{path.name}"
    return out


def _tag(ns: str, value: str, source="auto", conf=None) -> dict:
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ns}:{value}")), "namespace": ns,
            "value": value, "source": source, "confidence": conf}


def _make_asset(project_id: str, scene, i: int, kind="image") -> dict:
    room, style, materials, objects, colors, caption = scene
    aid = str(uuid.uuid4())
    w, h = rng.choice([(1600, 1067), (1600, 1200), (1200, 1600), (1600, 900)])
    urls = _render(aid, colors, f"{room} · {style}", w, h)
    phase = "existing conditions" if room == "site" else rng.choice(PHASES)
    tags = [_tag("room", room, conf=round(rng.uniform(0.82, 0.98), 2)),
            _tag("phase", phase, conf=round(rng.uniform(0.6, 0.9), 2)),
            _tag("style", style, conf=round(rng.uniform(0.7, 0.95), 2))]
    tags += [_tag("material", m, conf=round(rng.uniform(0.6, 0.95), 2)) for m in materials]
    tags += [_tag("object", o, conf=0.8) for o in objects]
    tags += [_tag("color", c, conf=0.9) for c in colors]
    if i % 4 == 0:
        tags.append(_tag("misc", "client favourite", source="manual"))
    created = now - timedelta(days=rng.randint(0, 120), hours=rng.randint(0, 23))
    asset = {
        "id": aid, "project_id": project_id, "kind": kind, "status": "ready",
        "filename": f"IMG_{4000 + i:04d}.heic" if kind == "image" else f"walkthrough_{i}.mov",
        "mime": "image/heic" if kind == "image" else "video/quicktime",
        "bytes": rng.randint(2_000_000, 9_000_000), "width": w, "height": h, "duration_s": None,
        "internal_only": room == "site" and i % 2 == 0, "captured_at": created.isoformat(),
        "created_at": created.isoformat(), "uploader_id": USER["id"],
        "caption": caption, "ocr_text": "SAMPLE A-204 / TRAVERTINE" if "travertine" in materials else None,
        "colors": colors, "tags": tags, "thumb_url": urls["thumb"], "preview_url": urls["preview"],
        "derived": [{"variant": "thumb", "url": urls["thumb"], "width": 256, "height": None, "timestamp_s": None},
                    {"variant": "preview", "url": urls["preview"], "width": w, "height": h, "timestamp_s": None}],
        "failure_reason": None, "favorited": False,
    }
    return asset


def _make_video(project_id: str) -> dict | None:
    if not which("ffmpeg"):
        return None
    aid = str(uuid.uuid4())
    path = MEDIA / f"{aid}_preview.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=1280x720:rate=24:duration=6", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-movflags", "+faststart", str(path)], check=False)
    if not path.exists():
        return None
    a = _make_asset(project_id, SCENES[3], 99)
    poster = a["thumb_url"].replace("_thumb", "_preview")
    a.update({
        "id": aid, "kind": "video", "filename": "lobby_walkthrough.mov", "mime": "video/quicktime",
        "duration_s": 6.0, "width": 1280, "height": 720, "bytes": 184_000_000,
        "caption": "Walkthrough from the street entry through the lobby to the elevator bank; marble desk and bronze reveals visible from 0:02.",
        "preview_url": f"{BASE}/media/{path.name}",
        "derived": [{"variant": "poster", "url": poster, "width": 1280, "height": 720, "timestamp_s": None},
                    {"variant": "thumb", "url": a["thumb_url"], "width": 256, "height": None, "timestamp_s": None},
                    {"variant": "preview", "url": f"{BASE}/media/{path.name}", "width": 1280, "height": 720, "timestamp_s": None},
                    {"variant": "keyframe_000", "url": poster, "width": 1280, "height": 720, "timestamp_s": 0.0},
                    {"variant": "keyframe_001", "url": poster, "width": 1280, "height": 720, "timestamp_s": 2.5}],
    })
    return a


def seed() -> None:
    pids = list(PROJECTS)
    i = 0
    for pid, n in zip(pids, (10, 6, 5)):
        for _ in range(n):
            a = _make_asset(pid, SCENES[i % len(SCENES)], i)
            ASSETS[a["id"]] = a
            i += 1
    v = _make_video(pids[1])
    if v:
        ASSETS[v["id"]] = v
    processing = _make_asset(pids[0], SCENES[0], 50)
    processing.update({"status": "processing", "caption": None, "tags": [], "colors": None,
                       "thumb_url": None, "preview_url": None, "derived": [], "_ready_at": time.time() + 20})
    ASSETS[processing["id"]] = processing
    for a in list(ASSETS.values())[:3]:
        FAVORITES.add(a["id"])
    first = list(ASSETS.values())
    COMMENTS[first[0]["id"]] = [
        {"id": str(uuid.uuid4()), "asset_id": first[0]["id"], "author_id": CLIENT["id"],
         "author_name": CLIENT["email"], "body": "Love the brass here. Could the stools be a darker wood?",
         "created_at": (now - timedelta(days=2)).isoformat()},
        {"id": str(uuid.uuid4()), "asset_id": first[0]["id"], "author_id": USER["id"],
         "author_name": USER["name"], "body": "Yes, we'll price a smoked oak option.",
         "created_at": (now - timedelta(days=1)).isoformat()},
    ]
    b = {"id": str(uuid.uuid4()), "project_id": pids[0], "name": "Kitchen references",
         "shared_with_clients": True, "created_by": USER["id"],
         "created_at": (now - timedelta(days=5)).isoformat()}
    BOARDS[b["id"]] = b
    BOARD_ASSETS[b["id"]] = [a["id"] for a in first if a["project_id"] == pids[0]][:5]


seed()
app.mount("/media", StaticFiles(directory=MEDIA), name="media")


# --- helpers -----------------------------------------------------------------


def _out(a: dict) -> dict:
    _settle(a)
    return {**{k: v for k, v in a.items() if not k.startswith("_")}, "favorited": a["id"] in FAVORITES}


def _project_out(p: dict) -> dict:
    return {**p, "asset_count": sum(1 for a in ASSETS.values() if a["project_id"] == p["id"])}


def _board_out(b: dict) -> dict:
    ids = BOARD_ASSETS.get(b["id"], [])
    cover = ASSETS[ids[0]]["thumb_url"] if ids and ids[0] in ASSETS else None
    return {**b, "asset_count": len(ids), "cover_url": cover}


def _get(aid: str) -> dict:
    a = ASSETS.get(aid)
    if a is None:
        raise HTTPException(404, "asset not found")
    return a


# --- auth / me ---------------------------------------------------------------


@app.post("/auth/magic-link", status_code=202)
def magic_link(body: dict):
    return {"status": "sent"}


@app.post("/auth/logout", status_code=204)
def logout():
    return Response(status_code=204)


@app.get("/me")
def me():
    return {**USER, "memberships": [{"firm_id": FIRM["id"], "firm_name": FIRM["name"],
                                    "firm_slug": FIRM["slug"], "role": "admin"}],
            "active_firm_id": FIRM["id"]}


# --- projects ----------------------------------------------------------------


@app.get("/firms/{firm_id}/projects")
def projects(firm_id: str):
    return [_project_out(p) for p in PROJECTS.values()]


@app.post("/firms/{firm_id}/projects", status_code=201)
def create_project(firm_id: str, body: dict):
    p = {"id": str(uuid.uuid4()), "firm_id": FIRM["id"], "name": body["name"],
         "client_label": body.get("client_label"), "phase": body.get("phase"), "status": "active",
         "created_at": now.isoformat()}
    PROJECTS[p["id"]] = p
    return _project_out(p)


@app.get("/projects/{pid}")
def project(pid: str):
    if pid not in PROJECTS:
        raise HTTPException(404, "project not found")
    return _project_out(PROJECTS[pid])


@app.patch("/projects/{pid}")
def update_project(pid: str, body: dict):
    PROJECTS[pid].update({k: v for k, v in body.items() if v is not None})
    return _project_out(PROJECTS[pid])


ACCESS = [{"user_id": CLIENT["id"], "email": CLIENT["email"], "name": None, "role": "viewer"}]


@app.get("/projects/{pid}/access")
def access(pid: str):
    return ACCESS


@app.post("/projects/{pid}/access", status_code=201)
def invite(pid: str, body: dict):
    row = {"user_id": str(uuid.uuid4()), "email": body["email"], "name": None, "role": body.get("role", "viewer")}
    ACCESS.append(row)
    return row


@app.delete("/projects/{pid}/access/{uid}", status_code=204)
def revoke(pid: str, uid: str):
    ACCESS[:] = [r for r in ACCESS if r["user_id"] != uid]
    return Response(status_code=204)


# --- uploads -----------------------------------------------------------------


def _variant(name: str, url: str, w: int | None, h: int | None, ts: float | None = None) -> dict:
    return {"variant": name, "url": url, "width": w, "height": h, "timestamp_s": ts}


PROCESSING_DELAY_S = 2.0  # keep "processing" visible briefly so the UI's polling path is exercised


def _process_image(aid: str, src: Path) -> dict:
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    w, h = img.size
    small = img.copy()
    small.thumbnail((64, 64))
    q = small.quantize(colors=3, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    by_freq = sorted(q.getcolors() or [], reverse=True)
    colors = [f"#{pal[i * 3]:02x}{pal[i * 3 + 1]:02x}{pal[i * 3 + 2]:02x}" for _, i in by_freq[:3]]
    urls = {}
    for variant, size in (("preview", 1600), ("thumb", 256)):
        copy = img.copy()
        copy.thumbnail((size, size))
        path = MEDIA / f"{aid}_{variant}.webp"
        copy.save(path, "WEBP", quality=80)
        urls[variant] = f"{BASE}/media/{path.name}"
    return {
        "width": w, "height": h, "colors": colors, "thumb_url": urls["thumb"], "preview_url": urls["preview"],
        "derived": [_variant("thumb", urls["thumb"], 256, None), _variant("preview", urls["preview"], w, h)],
    }


def _process_video(aid: str, src: Path) -> dict:
    if not which("ffmpeg") or not which("ffprobe"):
        raise RuntimeError("ffmpeg is not installed")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:format=duration", "-of", "json", str(src)],
                           capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    stream = (info.get("streams") or [{}])[0]
    w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
    duration = float((info.get("format") or {}).get("duration") or 0.0)
    preview = MEDIA / f"{aid}_preview.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", "scale='min(1280,iw)':-2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-movflags", "+faststart", str(preview)], check=True)
    frame = MEDIA / f"{aid}_frame.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(min(0.5, duration / 2)), "-i", str(src),
                    "-frames:v", "1", str(frame)], check=True)
    img_out = _process_image(aid, frame)
    poster = img_out["preview_url"]
    preview_url = f"{BASE}/media/{preview.name}"
    return {
        "width": w or img_out["width"], "height": h or img_out["height"], "duration_s": round(duration, 2),
        "colors": img_out["colors"], "thumb_url": img_out["thumb_url"], "preview_url": preview_url,
        "derived": [_variant("poster", poster, w, h), _variant("thumb", img_out["thumb_url"], 256, None),
                    _variant("preview", preview_url, w, h), _variant("keyframe_000", poster, w, h, 0.0)],
    }


def _enrich(aid: str, src: Path) -> None:
    """Runs on a worker thread after the upload completes; stands in for the image/video queues."""
    a = ASSETS.get(aid)
    if a is None:
        return
    try:
        result = _process_video(aid, src) if a["kind"] == "video" else _process_image(aid, src)
        scene = rng.choice(SCENES)  # fake "vision" output; the real backend asks Claude
        room, style, materials, objects, _colors, caption = scene
        tags = [_tag("room", room, conf=0.9), _tag("phase", rng.choice(PHASES), conf=0.7),
                _tag("style", style, conf=0.8)]
        tags += [_tag("material", m, conf=0.7) for m in materials]
        tags += [_tag("object", o, conf=0.8) for o in objects]
        tags += [_tag("color", c, conf=0.9) for c in result["colors"]]
        a["_result"] = {**result, "caption": caption, "tags": tags}
    except Exception as e:  # noqa: BLE001
        a["_result"] = {"status": "failed", "failure_reason": f"{type(e).__name__}: {e}"}


def _settle(a: dict) -> None:
    """Advance a processing asset once its worker finished and the minimum delay passed."""
    if a.get("status") != "processing" or time.time() < a.get("_ready_at", 0):
        return
    result = a.pop("_result", None)
    if result is None:
        if "_src" in a:  # upload still being processed by the worker thread
            return
        fresh = _make_asset(a["project_id"], rng.choice(SCENES), rng.randint(100, 999))  # seeded placeholder
        keep = {k: a[k] for k in ("id", "filename", "mime", "bytes", "created_at", "project_id")}
        a.clear()
        a.update({**fresh, **keep})
    else:
        a.update({"status": "ready", **result})
    a.pop("_src", None)


@app.post("/uploads", status_code=201)
def start_upload(body: dict):
    aid = str(uuid.uuid4())
    kind = "video" if str(body.get("mime", "")).startswith("video/") else "image"
    ASSETS[aid] = {
        "id": aid, "project_id": body["project_id"], "kind": kind, "status": "uploading",
        "filename": body["filename"], "mime": body["mime"], "bytes": body["size"],
        "width": None, "height": None, "duration_s": None, "internal_only": False, "captured_at": None,
        "created_at": datetime.now(UTC).isoformat(),
        "uploader_id": USER["id"], "caption": None, "ocr_text": None, "colors": None, "tags": [],
        "thumb_url": None, "preview_url": None, "derived": [], "failure_reason": None, "favorited": False,
    }
    part_size = 64 * 1024 * 1024
    n = max(1, math.ceil(body["size"] / part_size))
    return {"asset_id": aid, "upload_id": "mock", "part_size": part_size,
            "part_urls": [f"{BASE}/mock-s3/{aid}/{i}" for i in range(1, n + 1)], "deduplicated": False}


@app.put("/mock-s3/{aid}/{part}")
async def put_part(aid: str, part: int, request: Request):
    _get(aid)
    (MEDIA / f"{aid}.part{part:04d}").write_bytes(await request.body())
    return Response(status_code=200, headers={"ETag": f'"etag-{part}"'})


@app.post("/uploads/{aid}/complete", status_code=202)
def complete_upload(aid: str, body: dict):
    a = _get(aid)
    parts = sorted(MEDIA.glob(f"{aid}.part*"))
    ext = Path(a["filename"]).suffix.lower() or ""
    src = MEDIA / f"{aid}_original{ext}"
    with open(src, "wb") as out:
        for part in parts:
            out.write(part.read_bytes())
            part.unlink()
    a.update({"status": "processing", "_src": str(src), "_ready_at": time.time() + PROCESSING_DELAY_S})
    threading.Thread(target=_enrich, args=(aid, src), daemon=True).start()
    return {"status": "processing", "deferred": False}


@app.delete("/uploads/{aid}", status_code=204)
def abort_upload(aid: str):
    ASSETS.pop(aid, None)
    for part in MEDIA.glob(f"{aid}.part*"):
        part.unlink()
    return Response(status_code=204)


# --- assets ------------------------------------------------------------------


@app.get("/assets")
def list_assets(project_id: str | None = None, limit: int = 50, cursor: str | None = None):
    rows = [a for a in ASSETS.values() if project_id is None or a["project_id"] == project_id]
    rows.sort(key=lambda a: a["created_at"], reverse=True)
    return {"items": [_out(a) for a in rows[:limit]], "next_cursor": None}


@app.get("/assets/{aid}")
def get_asset(aid: str):
    return _out(_get(aid))


@app.patch("/assets/{aid}")
def update_asset(aid: str, body: dict):
    a = _get(aid)
    for k in ("caption", "internal_only", "captured_at", "project_id"):
        if k in body and body[k] is not None:
            a[k] = body[k]
    return _out(a)


@app.delete("/assets/{aid}", status_code=204)
def delete_asset(aid: str):
    ASSETS.pop(aid, None)
    return Response(status_code=204)


@app.get("/assets/{aid}/download")
def download(aid: str):
    a = _get(aid)
    return {"url": a["preview_url"] or "", "expires_in": 900}


@app.post("/assets/{aid}/tags", status_code=201)
def add_tag(aid: str, body: dict):
    a = _get(aid)
    t = _tag(body["namespace"], body["value"].lower(), source="manual")
    a["tags"] = [x for x in a["tags"] if x["id"] != t["id"]] + [t]
    return t


@app.delete("/assets/{aid}/tags/{tid}", status_code=204)
def remove_tag(aid: str, tid: str):
    a = _get(aid)
    a["tags"] = [x for x in a["tags"] if x["id"] != tid]
    return Response(status_code=204)


@app.post("/assets/{aid}/reprocess", status_code=202)
def reprocess(aid: str):
    a = _get(aid)
    a["status"] = "processing"
    a["_polls"] = 0
    return {"status": "processing", "deferred": False}


@app.put("/assets/{aid}/favorite", status_code=204)
def favorite(aid: str):
    FAVORITES.add(_get(aid)["id"])
    return Response(status_code=204)


@app.delete("/assets/{aid}/favorite", status_code=204)
def unfavorite(aid: str):
    FAVORITES.discard(aid)
    return Response(status_code=204)


@app.get("/assets/{aid}/comments")
def comments(aid: str):
    return COMMENTS.get(aid, [])


@app.post("/assets/{aid}/comments", status_code=201)
def add_comment(aid: str, body: dict):
    c = {"id": str(uuid.uuid4()), "asset_id": aid, "author_id": USER["id"], "author_name": USER["name"],
         "body": body["body"], "created_at": datetime.now(UTC).isoformat()}
    COMMENTS.setdefault(aid, []).append(c)
    return c


# --- search ------------------------------------------------------------------

TAG_NS = ("room", "phase", "style", "material", "color", "object")


def _matches_filters(a: dict, f: dict) -> bool:
    if f.get("project_id") and a["project_id"] not in f["project_id"]:
        return False
    if f.get("kind") and a["kind"] != f["kind"]:
        return False
    if f.get("favorites_only") and a["id"] not in FAVORITES:
        return False
    tags = {(t["namespace"], t["value"]) for t in a["tags"]}
    for ns in TAG_NS:
        wanted = f.get(ns)
        if wanted and not any((ns, v.lower()) in tags for v in wanted):
            return False
    return True


@app.post("/search")
def search(body: dict):
    f = body.get("filters") or {}
    q = (body.get("q") or "").lower().strip()
    similar = body.get("similar_to")
    rows = [a for a in ASSETS.values() if _matches_filters(a, f)]
    if similar:
        src = _get(similar)
        rooms = {t["value"] for t in src["tags"] if t["namespace"] == "room"}
        styles = {t["value"] for t in src["tags"] if t["namespace"] == "style"}
        hits = []
        for a in rows:
            if a["id"] == similar:
                continue
            at = {t["value"] for t in a["tags"]}
            score = 0.55 + 0.3 * bool(rooms & at) + 0.15 * bool(styles & at)
            hits.append((score, a, []))
        hits.sort(key=lambda h: -h[0])
        return {"mode": "similar", "next_cursor": None,
                "hits": [{"asset": _out(a), "score": round(s, 3), "matched_tags": m, "matched_timestamp_s": None}
                         for s, a, m in hits[: body.get("limit", 50)]]}
    if q:
        words = [w for w in q.replace(",", " ").split() if len(w) > 2]
        hits = []
        for a in rows:
            text = " ".join([a.get("caption") or ""] + [t["value"] for t in a["tags"]]).lower()
            matched = sorted({f'{t["namespace"]}:{t["value"]}' for t in a["tags"]
                              if any(w in t["value"] for w in words)})
            n = sum(1 for w in words if w in text)
            if n:
                hits.append((0.5 + 0.5 * n / len(words), a, matched))
        hits.sort(key=lambda h: (-h[0], h[1]["created_at"]))
        return {"mode": "semantic", "next_cursor": None,
                "hits": [{"asset": _out(a), "score": round(s, 3), "matched_tags": m, "matched_timestamp_s": None}
                         for s, a, m in hits[: body.get("limit", 50)]]}
    rows.sort(key=lambda a: a["created_at"], reverse=True)
    return {"mode": "browse", "next_cursor": None,
            "hits": [{"asset": _out(a), "score": 0.0, "matched_tags": [], "matched_timestamp_s": None}
                     for a in rows[: body.get("limit", 50)]]}


@app.get("/search/facets")
def facets(project_id: list[str] | None = Query(default=None)):
    counts: dict[str, dict[str, int]] = {}
    for a in ASSETS.values():
        if project_id and a["project_id"] not in project_id:
            continue
        for t in a["tags"]:
            counts.setdefault(t["namespace"], {})
            counts[t["namespace"]][t["value"]] = counts[t["namespace"]].get(t["value"], 0) + 1
    return {"facets": {ns: [{"value": v, "count": n} for v, n in sorted(vals.items(), key=lambda x: -x[1])]
                       for ns, vals in counts.items()}}


# --- boards ------------------------------------------------------------------


@app.get("/boards")
def boards(project_id: str | None = None):
    return [_board_out(b) for b in BOARDS.values() if project_id is None or b["project_id"] == project_id]


@app.post("/boards", status_code=201)
def create_board(body: dict):
    b = {"id": str(uuid.uuid4()), "project_id": body["project_id"], "name": body["name"],
         "shared_with_clients": False, "created_by": USER["id"], "created_at": datetime.now(UTC).isoformat()}
    BOARDS[b["id"]] = b
    BOARD_ASSETS[b["id"]] = []
    return _board_out(b)


@app.get("/boards/{bid}")
def board(bid: str):
    if bid not in BOARDS:
        raise HTTPException(404, "board not found")
    return _board_out(BOARDS[bid])


@app.patch("/boards/{bid}")
def update_board(bid: str, body: dict):
    BOARDS[bid].update({k: v for k, v in body.items() if v is not None})
    return _board_out(BOARDS[bid])


@app.delete("/boards/{bid}", status_code=204)
def delete_board(bid: str):
    BOARDS.pop(bid, None)
    BOARD_ASSETS.pop(bid, None)
    return Response(status_code=204)


@app.get("/boards/{bid}/assets")
def board_assets(bid: str):
    return [_out(ASSETS[a]) for a in BOARD_ASSETS.get(bid, []) if a in ASSETS]


@app.put("/boards/{bid}/assets", status_code=204)
def set_board_assets(bid: str, body: dict):
    BOARD_ASSETS[bid] = list(dict.fromkeys(body["asset_ids"]))
    return Response(status_code=204)


@app.post("/boards/{bid}/assets", status_code=204)
def add_board_assets(bid: str, body: dict):
    cur = BOARD_ASSETS.setdefault(bid, [])
    cur.extend(a for a in body["asset_ids"] if a not in cur)
    return Response(status_code=204)


if __name__ == "__main__":
    print(f"mock media in {MEDIA}; {len(ASSETS)} assets across {len(PROJECTS)} projects")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
