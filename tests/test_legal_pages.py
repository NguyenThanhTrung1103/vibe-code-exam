"""Phase 12 — public legal pages + footer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "slug,expected_title",
    [
        ("disclaimer", "Disclaimer"),
        ("terms", "Terms of Service"),
        ("privacy", "Privacy Policy"),
        ("dmca", "DMCA"),
    ],
)
def test_legal_page_renders(healthy_client: TestClient, slug: str, expected_title: str) -> None:
    r = healthy_client.get(f"/legal/{slug}")
    assert r.status_code == 200
    assert expected_title in r.text


def test_legal_404_for_unknown_slug(healthy_client: TestClient) -> None:
    r = healthy_client.get("/legal/not-a-real-page")
    assert r.status_code == 404


def test_footer_links_present_on_legal_page(healthy_client: TestClient) -> None:
    """Every page extends base.html, which includes the legal footer.

    Hit a DB-free route (`/legal/disclaimer`) so the test stays
    hermetic — the home page hits the catalog and is exercised by the
    real-DB suite instead.
    """
    r = healthy_client.get("/legal/disclaimer")
    assert r.status_code == 200
    body = r.text
    for href in ("/legal/disclaimer", "/legal/terms", "/legal/privacy", "/legal/dmca"):
        assert href in body, f"footer missing {href}"


def test_legal_pages_carry_security_headers(healthy_client: TestClient) -> None:
    r = healthy_client.get("/legal/disclaimer")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
