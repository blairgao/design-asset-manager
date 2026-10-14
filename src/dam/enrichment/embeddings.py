"""Embedding provider adapter (ADR-007). Every vector row records which model made it."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import Protocol

import httpx
import numpy as np

from dam.config import get_settings


class Embedder(Protocol):
    model: str
    dim: int

    def embed_images(self, images: list[bytes], media_type: str = "image/webp") -> list[list[float]]: ...

    def embed_text(self, texts: list[str]) -> list[list[float]]: ...


class VoyageMultimodalEmbedder:
    """Voyage AI multimodal embeddings: text and images share one space."""

    def __init__(self, api_key: str, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self._client = httpx.Client(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    def _call(self, inputs: list[dict], input_type: str) -> list[list[float]]:
        resp = self._client.post(
            "/multimodalembeddings",
            json={"inputs": inputs, "model": self.model, "input_type": input_type},
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def embed_images(self, images: list[bytes], media_type: str = "image/webp") -> list[list[float]]:
        inputs = [
            {
                "content": [
                    {
                        "type": "image_base64",
                        "image_base64": f"data:{media_type};base64,{base64.b64encode(b).decode()}",
                    }
                ]
            }
            for b in images
        ]
        out: list[list[float]] = []
        for i in range(0, len(inputs), 8):
            out.extend(self._call(inputs[i : i + 8], "document"))
        return out

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        inputs = [{"content": [{"type": "text", "text": t}]} for t in texts]
        return self._call(inputs, "query")


class FakeEmbedder:
    """Deterministic hash-based vectors for tests and local development without keys.

    Not semantically meaningful, but identical inputs produce identical vectors, so
    similar-image search and dedupe paths are exercisable end to end.
    """

    model = "fake-hash"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _vec(self, data: bytes) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(data).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim)
        v /= np.linalg.norm(v)
        return v.astype(float).tolist()

    def embed_images(self, images: list[bytes], media_type: str = "image/webp") -> list[list[float]]:
        return [self._vec(b) for b in images]

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t.lower().strip().encode()) for t in texts]


def mean_pool(vectors: list[list[float]]) -> list[float]:
    arr = np.asarray(vectors, dtype=float)
    m = arr.mean(axis=0)
    norm = np.linalg.norm(m)
    return (m / norm if norm else m).tolist()


@lru_cache
def get_embedder() -> Embedder:
    import os

    settings = get_settings()
    if settings.embedding_provider == "fake":
        return FakeEmbedder(settings.embedding_dim)
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise RuntimeError("VOYAGE_API_KEY is required when DAM_EMBEDDING_PROVIDER=voyage")
    return VoyageMultimodalEmbedder(key, settings.embedding_model, settings.embedding_dim)
