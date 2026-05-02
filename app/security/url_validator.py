"""Phase 13 — SSRF guard for community-signal URLs (syntactic + IP-literal layer).

Used by the import normalizer (Phase 13) to validate `discussion_url` before
storing it in `community_discussion_sources`. Phase 14 fetcher will reuse the
same `validate_url` and add DNS resolution + redirect-aware checks.

PHASE 13 SCOPE — syntactic validation only:
  * Parse + reject malformed URLs (length cap, control chars).
  * Scheme allowlist (default: https only; http permitted only for fixtures/tests
    via `allow_http=True`).
  * Reject IP-literal hosts on every blocklisted range (incl. CGNAT 100.64/10
    per red-team #2 — Tailscale subnet).
  * Reject suspicious hostnames ("localhost", "*.local", "*.internal").
  * Optional host allowlist (suffix-match) for the import path that wants
    "examtopics.com only".

DEFERRED TO PHASE 14:
  * DNS pinning + per-redirect re-validation (red-team #2 fix).
  * `follow_redirects=False` enforcement (httpx config).
  * Per-host rate limit / robots.txt.

Why split: Phase 13 does NOT perform any network IO. Adding DNS lookup here
would either be misleading (we never fetch) or block on slow DNS at import
time. Defending in depth means both layers run; Phase 13 catches IP literals
and obviously-unsafe URLs at write time, Phase 14 catches DNS-rebind /
redirect-to-private at fetch time.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

# RFC 1918, link-local, loopback, CGNAT, multicast, reserved, "this host".
_BLOCKED_IPV4_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("0.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("100.64.0.0/10"),  # CGNAT — Tailscale (red-team #2).
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.0.0.0/24"),
    ipaddress.IPv4Network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("198.18.0.0/15"),  # benchmark
    ipaddress.IPv4Network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.IPv4Network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.IPv4Network("224.0.0.0/4"),  # multicast
    ipaddress.IPv4Network("240.0.0.0/4"),  # reserved
    ipaddress.IPv4Network("255.255.255.255/32"),  # limited broadcast
)

_BLOCKED_IPV6_NETWORKS: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.IPv6Network("::/128"),  # unspecified
    ipaddress.IPv6Network("::1/128"),  # loopback
    ipaddress.IPv6Network("::ffff:0:0/96"),  # IPv4-mapped IPv6 (red-team #2)
    ipaddress.IPv6Network("64:ff9b::/96"),  # IPv4-IPv6 translation
    ipaddress.IPv6Network("100::/64"),  # discard
    ipaddress.IPv6Network("fc00::/7"),  # unique local (RFC 4193)
    ipaddress.IPv6Network("fe80::/10"),  # link-local
    ipaddress.IPv6Network("ff00::/8"),  # multicast
)

_ALLOWED_SCHEMES_HTTPS_ONLY = ("https",)
_ALLOWED_SCHEMES_BOTH = ("http", "https")

_SUSPICIOUS_HOSTNAMES = re.compile(
    r"^(localhost|.*\.local|.*\.internal|.*\.localdomain|.*\.lan|.*\.test|.*\.example)$",
    re.IGNORECASE,
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MAX_URL_LENGTH = 2048


class BlockedURLError(ValueError):
    """Raised when a URL fails any of the Phase-13 SSRF guard checks."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"blocked_url: {reason}")
        self.url = url
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ValidatedURL:
    """Outcome of a successful `validate_url` call.

    `parsed` is `urllib.parse`'s `SplitResult` (returned by `urlsplit`) so
    callers can inspect host, scheme, etc. without re-parsing.
    """

    raw: str
    parsed: SplitResult


def validate_url(
    url: str,
    *,
    allow_http: bool = False,
    allowed_host_suffixes: tuple[str, ...] | None = None,
) -> ValidatedURL:
    """Validate `url` syntactically.

    Args:
        url: candidate URL string.
        allow_http: when True, accept `http://` in addition to `https://`.
            Phase 13 uses False; tests/fixtures may relax it.
        allowed_host_suffixes: when given, host must end with one of these
            suffixes (case-insensitive, leading dot OR exact match).

    Returns:
        `ValidatedURL` on success.

    Raises:
        `BlockedURLError` on any failure with a stable `.reason` string for
        audit/UX display. The reason set is closed (no PII / no host echo
        beyond what was already in the URL).
    """
    if not isinstance(url, str) or not url:
        raise BlockedURLError(str(url), "empty")
    if len(url) > _MAX_URL_LENGTH:
        raise BlockedURLError(url, f"too_long ({len(url)}>{_MAX_URL_LENGTH})")
    if _CONTROL_CHARS.search(url):
        raise BlockedURLError(url, "control_chars")

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise BlockedURLError(url, f"unparseable: {exc.__class__.__name__}") from exc

    schemes = _ALLOWED_SCHEMES_BOTH if allow_http else _ALLOWED_SCHEMES_HTTPS_ONLY
    if parsed.scheme.lower() not in schemes:
        raise BlockedURLError(url, f"scheme_not_allowed: {parsed.scheme!r}")

    if not parsed.hostname:
        raise BlockedURLError(url, "no_host")

    host = parsed.hostname.lower()

    # Some platforms allow scoped-link literals like "fe80::1%eth0"; strip the
    # zone-id before parsing as IPv6.
    if "%" in host:
        host = host.split("%", 1)[0]

    if _SUSPICIOUS_HOSTNAMES.match(host):
        raise BlockedURLError(url, "suspicious_hostname")

    # IP-literal host: enforce blocklist.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if isinstance(ip, ipaddress.IPv4Address):
            for net4 in _BLOCKED_IPV4_NETWORKS:
                if ip in net4:
                    raise BlockedURLError(url, f"blocked_ipv4: {net4}")
        else:
            for net6 in _BLOCKED_IPV6_NETWORKS:
                if ip in net6:
                    raise BlockedURLError(url, f"blocked_ipv6: {net6}")

    if allowed_host_suffixes:
        ok = False
        for suffix in allowed_host_suffixes:
            s = suffix.lower().lstrip(".")
            if host == s or host.endswith("." + s):
                ok = True
                break
        if not ok:
            raise BlockedURLError(url, "host_not_in_allowlist")

    return ValidatedURL(raw=url, parsed=parsed)


__all__ = ["BlockedURLError", "ValidatedURL", "validate_url"]
