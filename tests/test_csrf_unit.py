"""CSRF token issue + verify — pure unit tests."""

from __future__ import annotations

from fastapi import Request, Response

from app.auth.csrf import CSRF_COOKIE_NAME, issue_csrf_token, verify_csrf


def _request_with_csrf_cookie(token: str | None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if token is not None:
        headers.append((b"cookie", f"{CSRF_COOKIE_NAME}={token}".encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


def test_csrf_round_trip_accepts_matching_form_field() -> None:
    response = Response()
    token = issue_csrf_token(response)
    assert token  # non-empty
    request = _request_with_csrf_cookie(token)
    assert verify_csrf(request, token) is True


def test_csrf_rejects_missing_form_field() -> None:
    response = Response()
    token = issue_csrf_token(response)
    request = _request_with_csrf_cookie(token)
    assert verify_csrf(request, "") is False
    assert verify_csrf(request, None) is False


def test_csrf_rejects_missing_cookie() -> None:
    response = Response()
    token = issue_csrf_token(response)
    request = _request_with_csrf_cookie(None)
    assert verify_csrf(request, token) is False


def test_csrf_rejects_mismatched_form_field() -> None:
    response = Response()
    token = issue_csrf_token(response)
    request = _request_with_csrf_cookie(token)
    assert verify_csrf(request, token + "x") is False


def test_csrf_rejects_tampered_cookie() -> None:
    response = Response()
    token = issue_csrf_token(response)
    tampered_request = _request_with_csrf_cookie(token + "x")
    assert verify_csrf(tampered_request, token + "x") is False
