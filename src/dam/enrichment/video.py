"""Video probing, keyframe extraction, and preview transcoding with ffmpeg (ADR-008)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dam.config import get_settings


@dataclass
class VideoProbe:
    width: int
    height: int
    duration_s: float
    codec: str


@dataclass
class Keyframe:
    index: int
    timestamp_s: float
    path: Path


def _run(cmd: list[str], *, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def probe(path: Path) -> VideoProbe:
    res = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr.strip()[:400]}")
    info = json.loads(res.stdout)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("no video stream")
    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    width, height = int(video["width"]), int(video["height"])
    rotation = _rotation(video)
    if rotation in (90, 270):
        width, height = height, width
    return VideoProbe(width=width, height=height, duration_s=duration, codec=video.get("codec_name", ""))


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            return abs(int(sd["rotation"])) % 360
    return abs(int(stream.get("tags", {}).get("rotate", 0))) % 360


_showinfo_pts = re.compile(r"pts_time:\s*([0-9.]+)")


def select_timestamps(
    scene_changes: list[float], duration_s: float, *, min_interval: float, max_frames: int
) -> list[float]:
    """Enforce the minimum spacing and the cap, and fall back to even sampling when a video
    has too few scene changes to be useful."""
    # Always start at the first frame (it becomes the poster), then keep scene changes that are
    # at least min_interval apart.
    picked: list[float] = [0.0]
    for t in sorted(scene_changes):
        if t - picked[-1] >= min_interval:
            picked.append(t)
    if len(picked) < 3 and duration_s > min_interval:
        n = int(duration_s // min_interval) + 1
        picked = sorted(set(picked) | {round(i * min_interval, 3) for i in range(n)})
    if len(picked) > max_frames:
        step = len(picked) / max_frames
        picked = [picked[int(i * step)] for i in range(max_frames)]
    return picked


def extract_keyframes(path: Path, workdir: Path, duration_s: float) -> list[Keyframe]:
    settings = get_settings()
    # Pass 1: detect scene changes (timestamps only).
    res = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            f"select='gt(scene,{settings.video_scene_threshold})',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    scene_changes = [float(m) for m in _showinfo_pts.findall(res.stderr)]
    timestamps = select_timestamps(
        scene_changes,
        duration_s,
        min_interval=settings.video_keyframe_min_interval_s,
        max_frames=settings.video_keyframe_max,
    )
    # Pass 2: grab one frame per chosen timestamp.
    frames: list[Keyframe] = []
    for i, t in enumerate(timestamps):
        out = workdir / f"kf_{i:03d}.jpg"
        res = _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-y",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-vf",
                "scale='min(1600,iw)':-2",
                str(out),
            ]
        )
        if res.returncode == 0 and out.exists() and out.stat().st_size > 0:
            frames.append(Keyframe(index=len(frames), timestamp_s=t, path=out))
    if not frames:
        raise RuntimeError("could not extract any keyframes")
    return frames


def transcode_preview(path: Path, out: Path) -> None:
    res = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(path),
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out),
        ],
        timeout=3600,
    )
    if res.returncode != 0:
        raise RuntimeError(f"preview transcode failed: {res.stderr.strip()[-400:]}")


def ffmpeg_available() -> bool:
    from shutil import which

    return which("ffmpeg") is not None and which("ffprobe") is not None


__all__ = [
    "probe",
    "extract_keyframes",
    "transcode_preview",
    "select_timestamps",
    "Keyframe",
    "VideoProbe",
    "ffmpeg_available",
    "os",
]
