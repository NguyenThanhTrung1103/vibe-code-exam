"""Pure-unit tests for auth primitives — no DB, no Redis."""

from __future__ import annotations

from fastapi import Request, Response

from app.auth.service import (
    hash_password,
    needs_rehash,
    verify_password,
)
from app.auth.session import (
    clear_session_cookie,
    issue_session_cookie,
    read_session_user_id,
)


def test_hash_and_verify_password_round_trip() -> None:
    h = hash_password("super-secret-passphrase-1234")
    assert h != "super-secret-passphrase-1234"
    assert verify_password("super-secret-passphrase-1234", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_handles_bogus_hash_gracefully() -> None:
    assert verify_password("anything", "not-an-argon2-hash") is False


def test_needs_rehash_false_for_fresh_hash() -> None:
    h = hash_password("super-secret-passphrase-1234")
    assert needs_rehash(h) is False


def _fake_request(cookie_value: str | None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"cookie", f"exam_session={cookie_value}".encode())] if cookie_value else [],
        "query_string": b"",
    }
    return Request(scope)


def test_session_cookie_round_trip() -> None:
    response = Response()
    issue_session_cookie(response, user_id=42)
    set_cookie_header = next(v for k, v in response.raw_headers if k == b"set-cookie").decode()
    # `exam_session=<token>; ...`
    token = set_cookie_header.split(";", 1)[0].split("=", 1)[1]

    request = _fake_request(token)
    assert read_session_user_id(request) == 42


def test_session_cookie_tampered_rejected() -> None:
    response = Response()
    issue_session_cookie(response, user_id=42)
    set_cookie_header = next(v for k, v in response.raw_headers if k == b"set-cookie").decode()
    tampered = set_cookie_header.split(";", 1)[0].split("=", 1)[1] + "x"
    assert read_session_user_id(_fake_request(tampered)) is None


def test_session_cookie_missing_returns_none() -> None:
    assert read_session_user_id(_fake_request(None)) is None


def test_clear_session_cookie_sets_max_age_zero() -> None:
    response = Response()
    clear_session_cookie(response)
    headers = [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]
    assert any("Max-Age=0" in h or "max-age=0" in h for h in headers)
