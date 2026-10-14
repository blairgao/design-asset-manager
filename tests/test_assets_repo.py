import uuid
from datetime import UTC, datetime

from dam.models import AssetKind
from dam.repositories.assets import decode_cursor, encode_cursor, kind_for_mime


def test_cursor_roundtrip():
    t = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    aid = uuid.uuid4()
    assert decode_cursor(encode_cursor(t, aid)) == (t, aid)
    assert decode_cursor(None) is None
    assert decode_cursor("not-base64!") is None


def test_kind_for_mime():
    assert kind_for_mime("image/jpeg") == AssetKind.image
    assert kind_for_mime("image/heic") == AssetKind.image
    assert kind_for_mime("video/quicktime") == AssetKind.video
    assert kind_for_mime("application/pdf") is None
