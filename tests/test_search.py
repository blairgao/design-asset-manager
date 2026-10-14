import uuid
from datetime import UTC, datetime, timedelta

from dam.repositories.search import (
    Candidate,
    decode_offset,
    encode_offset,
    extract_query_tags,
    recency_prior,
    rerank,
)

VOCAB = {
    "room": ["kitchen", "living room", "powder room"],
    "material": ["oak", "white oak", "terrazzo", "brass"],
    "style": ["mid-century", "modern"],
}


def test_extract_query_tags_matches_phrases_and_words():
    found = extract_query_tags("Warm white oak kitchen with brass fixtures, mid-century feel", VOCAB)
    assert ("room", "kitchen") in found
    assert ("material", "white oak") in found
    assert ("material", "oak") in found  # single word also matches inside the phrase
    assert ("material", "brass") in found
    assert ("style", "mid-century") in found
    assert ("room", "living room") not in found


def test_extract_query_tags_requires_whole_tokens():
    assert ("material", "oak") not in extract_query_tags("soaking tub", VOCAB)
    assert extract_query_tags("", VOCAB) == []


def test_rerank_prefers_tag_hits_and_recency_when_vectors_tie():
    now = datetime.now(UTC)
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    candidates = [Candidate(a, 0.3), Candidate(b, 0.3), Candidate(c, 0.3)]
    tags = {a: {("room", "kitchen")}, b: set(), c: {("room", "kitchen"), ("material", "oak")}}
    created = {a: now - timedelta(days=400), b: now, c: now - timedelta(days=400)}
    ranked = rerank(candidates, tags, created, [("room", "kitchen"), ("material", "oak")])
    assert [r.asset_id for r in ranked][0] == c
    assert ranked[0].matched_tags == ["material:oak", "room:kitchen"]
    # Full tag match beats recency alone.
    assert ranked[0].score > ranked[1].score > ranked[2].score


def test_rerank_vector_dominates():
    a, b = uuid.uuid4(), uuid.uuid4()
    ranked = rerank(
        [Candidate(a, 0.05), Candidate(b, 0.6)],
        {b: {("room", "kitchen")}},
        {a: datetime.now(UTC), b: datetime.now(UTC)},
        [("room", "kitchen")],
    )
    assert ranked[0].asset_id == a


def test_recency_prior_decays():
    now = datetime.now(UTC)
    assert recency_prior(now, now) == 1.0
    assert 0.3 < recency_prior(now - timedelta(days=365), now) < 0.4


def test_offset_cursor_roundtrip():
    assert decode_offset(encode_offset(150)) == 150
    assert decode_offset(None) == 0
    assert decode_offset("garbage") == 0
