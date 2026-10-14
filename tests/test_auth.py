import uuid

from dam.auth import issue_session, read_session


def test_session_roundtrip_and_tamper():
    uid = uuid.uuid4()
    cookie = issue_session(uid)
    assert read_session(cookie) == uid
    assert read_session(cookie[:-3] + "xyz") is None
    assert read_session(None) is None
    assert read_session("") is None
