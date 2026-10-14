import numpy as np

from dam.enrichment.embeddings import FakeEmbedder, get_embedder, mean_pool


def test_fake_embedder_is_deterministic_and_normalized():
    e = FakeEmbedder(64)
    a, b = e.embed_images([b"x", b"x"])
    assert a == b and abs(np.linalg.norm(a) - 1) < 1e-9
    assert e.embed_text(["Kitchen"])[0] == e.embed_text(["kitchen "])[0]
    assert e.embed_text(["kitchen"])[0] != e.embed_text(["lobby"])[0]


def test_mean_pool_normalizes():
    pooled = mean_pool([[1.0, 0.0], [0.0, 1.0]])
    assert abs(np.linalg.norm(pooled) - 1) < 1e-9


def test_settings_select_fake_provider():
    assert isinstance(get_embedder(), FakeEmbedder)
