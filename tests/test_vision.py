import json
from types import SimpleNamespace

import pytest

from dam.enrichment import vision

VOCAB = {
    "room": ["kitchen", "lobby"],
    "phase": ["concept", "completed"],
    "style": ["modern"],
    "material": ["oak", "brass"],
}


def test_schema_enforces_closed_vocabulary():
    schema = vision.output_schema(VOCAB, video=False)
    variants = schema["properties"]["tags"]["items"]["anyOf"]
    by_ns = {v["properties"]["namespace"]["const"]: v["properties"]["value"]["enum"] for v in variants}
    assert by_ns["room"] == ["kitchen", "lobby"]
    assert by_ns["material"] == ["brass", "oak"]
    assert schema["properties"]["moments"]["maxItems"] == 0
    assert vision.output_schema(VOCAB, video=True)["properties"]["moments"]["maxItems"] == 60


def test_prompt_hash_changes_with_vocabulary():
    assert vision.prompt_hash(VOCAB) != vision.prompt_hash({**VOCAB, "room": ["kitchen"]})
    assert vision.prompt_hash(VOCAB) == vision.prompt_hash(dict(reversed(list(VOCAB.items()))))


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _response(payload: dict, stop_reason="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        model=model,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=1200, output_tokens=150, cache_read_input_tokens=900),
    )


@pytest.fixture
def fake_client(monkeypatch):
    holder = {}

    def install(response):
        messages = _FakeMessages(response)
        client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
        monkeypatch.setattr(vision, "_client", lambda: client)
        holder["messages"] = messages
        return messages

    return install


def test_describe_parses_and_caps_tags(fake_client):
    payload = {
        "caption": "A bright kitchen.",
        "tags": [{"namespace": "room", "value": "kitchen", "confidence": 0.95}]
        + [{"namespace": "material", "value": "oak", "confidence": 0.5 + i / 100} for i in range(8)]
        + [{"namespace": "style", "value": "none", "confidence": 0.1}],
        "objects": ["island", "pendant light"],
        "ocr_text": "",
        "colors": ["#f2e8d5", "#8a5a2b"],
        "people_present": False,
        "moments": [],
    }
    messages = fake_client(_response(payload))
    result, usage = vision.describe(
        [b"img"], vocab=VOCAB, project_name="Loft", project_phase="concept", filename="IMG_1.jpg"
    )
    assert result.caption == "A bright kitchen."
    assert sum(1 for t in result.tags if t.namespace == "material") == vision.MAX_TAGS_PER_NAMESPACE
    assert all(t.value != "none" for t in result.tags)
    assert usage.input_tokens == 1200 and usage.cache_read_tokens == 900
    assert usage.prompt_hash == vision.prompt_hash(VOCAB)

    call = messages.calls[0]
    assert call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in call
    # Static prefix first, with the cache breakpoint on the vocabulary block.
    assert call["system"][0]["text"] == vision.SYSTEM_PROMPT
    assert call["system"][1]["cache_control"]["type"] == "ephemeral"
    user_content = call["messages"][0]["content"]
    assert user_content[0]["type"] == "text" and "Loft" in user_content[0]["text"]
    assert user_content[1]["type"] == "image"


def test_video_request_labels_keyframes(fake_client):
    payload = {
        "caption": "c",
        "tags": [],
        "objects": [],
        "ocr_text": "",
        "colors": [],
        "people_present": False,
        "moments": [{"frame_index": 1, "caption": "lobby"}],
    }
    messages = fake_client(_response(payload))
    result, _ = vision.describe(
        [b"a", b"b"],
        vocab=VOCAB,
        project_name="P",
        project_phase=None,
        filename="walk.mp4",
        video=True,
        frame_timestamps=[0.0, 5.0],
    )
    assert result.moments[0].frame_index == 1
    content = messages.calls[0]["messages"][0]["content"]
    assert [c["type"] for c in content] == ["text", "text", "image", "text", "image"]
    assert "Keyframe 1:" in content[3]["text"]


def test_refusal_raises_non_retryable(fake_client):
    fake_client(_response({}, stop_reason="refusal"))
    with pytest.raises(vision.VisionRefused):
        vision.describe([b"img"], vocab=VOCAB, project_name="P", project_phase=None, filename="x.jpg")
