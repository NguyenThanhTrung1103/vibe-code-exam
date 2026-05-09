"""Phase 13 — `url_validator` (SSRF guard, syntactic layer) unit tests.

Covers:
  * Happy path https URL.
  * Empty / non-string / None input.
  * Length cap, control chars.
  * Scheme allowlist (http only with `allow_http=True`).
  * Suspicious hostnames (localhost, *.local, *.internal, *.test, *.example).
  * IPv4 blocklist incl. CGNAT 100.64/10 (red-team #2 — Tailscale).
  * IPv6 blocklist incl. ::1, fc00::/7, fe80::/10, IPv4-mapped (::ffff:..).
  * IPv6 zone-id stripping (`fe80::1%eth0`).
  * Allowed-host suffix list (suffix + exact match).
  * Public IP literal allowed when not in blocklist (8.8.8.8).
  * `ValidatedURL` exposes raw + parsed.

NO network IO — DNS pinning is deferred to Phase 14 by design.
"""

from __future__ import annotations

import pytest

from app.security.url_validator import (
    BlockedURLError,
    ValidatedURL,
    validate_url,
)

# ---------------------------------------------------------------- happy path


def test_happy_path_https_url_passes() -> None:
    out = validate_url("https://www.examtopics.com/discussions/fortinet/view/x")
    assert isinstance(out, ValidatedURL)
    assert out.raw == "https://www.examtopics.com/discussions/fortinet/view/x"
    assert out.parsed.scheme == "https"
    assert out.parsed.hostname == "www.examtopics.com"


def test_public_ipv4_literal_not_in_blocklist_is_allowed() -> None:
    """8.8.8.8 is public — must pass syntactic SSRF guard."""
    out = validate_url("https://8.8.8.8/some/path")
    assert out.parsed.hostname == "8.8.8.8"


# ------------------------------------------------------------ malformed input


@pytest.mark.parametrize("bad", ["", None, 123, [], {}])
def test_empty_or_non_string_rejected(bad: object) -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(bad)  # type: ignore[arg-type]
    assert excinfo.value.reason == "empty"


def test_whitespace_only_string_falls_through_to_scheme_check() -> None:
    """Current behaviour: a non-empty whitespace string is truthy, so it
    bypasses the `not url` short-circuit and is rejected by the scheme
    check. Documenting the actual behavior, not endorsing it.
    """
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url("   ")
    assert excinfo.value.reason.startswith("scheme_not_allowed")


def test_too_long_url_rejected() -> None:
    big = "https://example.com/" + "a" * 4096
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(big)
    assert excinfo.value.reason.startswith("too_long")


def test_control_char_in_url_rejected() -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url("https://example.com/path\x00abc")
    assert excinfo.value.reason == "control_chars"


def test_url_without_host_rejected() -> None:
    """`https:///path` → empty hostname → no_host."""
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url("https:///just/a/path")
    assert excinfo.value.reason == "no_host"


# ----------------------------------------------------------------- schemes


def test_http_rejected_by_default() -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url("http://example.com/")
    assert excinfo.value.reason.startswith("scheme_not_allowed")


def test_http_allowed_when_flag_set() -> None:
    out = validate_url("http://example.com/", allow_http=True)
    assert out.parsed.scheme == "http"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "gopher://example.com/",
    ],
)
def test_other_schemes_always_rejected(url: str) -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(url, allow_http=True)  # even with allow_http
    assert excinfo.value.reason.startswith("scheme_not_allowed") or excinfo.value.reason in {
        "no_host",
    }


# --------------------------------------------------------- suspicious names


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "foo.local",
        "service.internal",
        "router.localdomain",
        "machine.lan",
        "node.test",
        "demo.example",
    ],
)
def test_suspicious_hostnames_rejected(host: str) -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(f"https://{host}/")
    assert excinfo.value.reason == "suspicious_hostname"


# ----------------------------------------------------------- IPv4 blocklist


@pytest.mark.parametrize(
    "ip,expected_net",
    [
        ("127.0.0.1", "127.0.0.0/8"),
        ("0.0.0.0", "0.0.0.0/8"),
        ("10.1.2.3", "10.0.0.0/8"),
        ("172.16.0.5", "172.16.0.0/12"),
        ("192.168.1.1", "192.168.0.0/16"),
        ("169.254.169.254", "169.254.0.0/16"),  # AWS metadata classic
        ("100.64.1.1", "100.64.0.0/10"),  # CGNAT — red-team #2
        ("100.127.255.254", "100.64.0.0/10"),  # CGNAT upper edge
        ("224.0.0.1", "224.0.0.0/4"),  # multicast
        # 255.255.255.255 is also in 240.0.0.0/4 (reserved); blocklist
        # iteration hits the broader range first, so reason reflects that.
        ("255.255.255.255", "240.0.0.0/4"),
        ("198.18.0.1", "198.18.0.0/15"),  # benchmark
    ],
)
def test_ipv4_blocklist_blocks_private_and_cgnat(ip: str, expected_net: str) -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(f"https://{ip}/path")
    assert excinfo.value.reason == f"blocked_ipv4: {expected_net}"


# ----------------------------------------------------------- IPv6 blocklist


@pytest.mark.parametrize(
    "url,expected_prefix",
    [
        ("https://[::1]/", "blocked_ipv6: ::1/128"),
        ("https://[fe80::1]/", "blocked_ipv6: fe80::/10"),
        ("https://[fc00::1]/", "blocked_ipv6: fc00::/7"),
        ("https://[ff00::1]/", "blocked_ipv6: ff00::/8"),
        # IPv4-mapped IPv6 "::ffff:192.168.1.1" — red-team #2 escape vector
        ("https://[::ffff:192.168.1.1]/", "blocked_ipv6: ::ffff:0.0.0.0/96"),
    ],
)
def test_ipv6_blocklist_blocks_loopback_link_local_unique_local(
    url: str, expected_prefix: str
) -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(url)
    assert excinfo.value.reason == expected_prefix


def test_ipv6_zone_id_stripped_then_blocked() -> None:
    """`fe80::1%eth0` should still hit the link-local block."""
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url("https://[fe80::1%25eth0]/path")
    assert "blocked_ipv6" in excinfo.value.reason


# --------------------------------------------------------- host allowlist


def test_allowlist_exact_match_passes() -> None:
    out = validate_url(
        "https://examtopics.com/x",
        allowed_host_suffixes=("examtopics.com",),
    )
    assert out.parsed.hostname == "examtopics.com"


def test_allowlist_subdomain_match_passes() -> None:
    out = validate_url(
        "https://www.examtopics.com/discussions/x",
        allowed_host_suffixes=("examtopics.com",),
    )
    assert out.parsed.hostname == "www.examtopics.com"


def test_allowlist_unrelated_host_rejected() -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(
            "https://evil.example.org/",
            allowed_host_suffixes=("examtopics.com",),
        )
    # Host matches `*.example` suspicious-name regex first; if not, allowlist.
    assert excinfo.value.reason in {"host_not_in_allowlist", "suspicious_hostname"}


def test_allowlist_almost_matching_host_rejected() -> None:
    """`examtopics.com.evil.io` must not pass the suffix check."""
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url(
            "https://examtopics.com.evil.io/",
            allowed_host_suffixes=("examtopics.com",),
        )
    assert excinfo.value.reason == "host_not_in_allowlist"


def test_allowlist_leading_dot_normalised() -> None:
    out = validate_url(
        "https://www.examtopics.com/",
        allowed_host_suffixes=(".examtopics.com",),
    )
    assert out.parsed.hostname == "www.examtopics.com"


# -------------------------------------------------------- BlockedURLError


def test_blocked_url_error_carries_url_and_reason() -> None:
    with pytest.raises(BlockedURLError) as excinfo:
        validate_url("https://127.0.0.1/")
    err = excinfo.value
    assert err.url == "https://127.0.0.1/"
    assert err.reason.startswith("blocked_ipv4")
    assert "blocked_url" in str(err)
