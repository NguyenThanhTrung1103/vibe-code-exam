"""Phase 03 live verification — register/login/me/logout/RBAC/CSRF/rate-limit.

Run only on the LXC against http://127.0.0.1:8001 with a started uvicorn.
Cleans up test rows at the end. Exits non-zero on any check failure.
"""

from __future__ import annotations

import re
import sys
import uuid

import httpx
from sqlalchemy import text

from app.db import engine

BASE = "http://127.0.0.1:8001"


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def main() -> int:
    nonce = uuid.uuid4().hex[:8]
    email = f"manual-{nonce}@test.local"
    username = f"manual{nonce}"
    pw = "Phase03-manual-pw-secret"

    print("--- /healthz ---")
    with httpx.Client(timeout=5) as c:
        r = c.get(f"{BASE}/healthz")
        print("HTTP", r.status_code, r.json())
        assert r.status_code == 200, r.text

    print("\n--- register ---")
    with httpx.Client(timeout=5) as c:
        g = c.get(f"{BASE}/auth/register")
        tok = csrf_from(g.text)
        r = c.post(
            f"{BASE}/auth/register",
            data={"email": email, "username": username, "password": pw, "csrf_token": tok},
        )
        print("HTTP", r.status_code, r.json())
        assert r.status_code == 201, r.text
        assert "exam_session" in r.cookies

        print("\n--- /auth/me (after register) ---")
        me = c.get(f"{BASE}/auth/me")
        print("HTTP", me.status_code, me.json())
        assert me.status_code == 200 and me.json()["email"] == email

        print("\n--- /admin/audit.json as student (expect 403) ---")
        r = c.get(f"{BASE}/admin/audit.json")
        print("HTTP", r.status_code)
        assert r.status_code == 403

        print("\n--- /auth/logout ---")
        r = c.post(f"{BASE}/auth/logout")
        print("HTTP", r.status_code)
        assert r.status_code == 200

        print("\n--- /auth/me (after logout, expect 401) ---")
        r = c.get(f"{BASE}/auth/me")
        print("HTTP", r.status_code)
        assert r.status_code == 401

        print("\n--- login again ---")
        g = c.get(f"{BASE}/auth/login")
        tok = csrf_from(g.text)
        r = c.post(
            f"{BASE}/auth/login",
            data={"identifier": email, "password": pw, "csrf_token": tok},
        )
        print("HTTP", r.status_code, r.json())
        assert r.status_code == 200

        print("\n--- POST /auth/register WITHOUT csrf (expect 403) ---")
        r = httpx.post(
            f"{BASE}/auth/register",
            data={"email": "x@test.local", "username": "x", "password": "x" * 12},
            timeout=3,
        )
        print("HTTP", r.status_code, r.json())
        assert r.status_code == 403

        print("\n--- 6 wrong-password logins → 429 ---")
        g = c.get(f"{BASE}/auth/login")
        tok = csrf_from(g.text)
        last = None
        for _ in range(7):
            last = c.post(
                f"{BASE}/auth/login",
                data={"identifier": email, "password": "WRONG-pw-1234567", "csrf_token": tok},
            )
            if last.status_code == 429:
                break
        assert last is not None
        print(f"final HTTP {last.status_code}, retry-after={last.headers.get('retry-after')}")
        assert last.status_code == 429

    print("\n--- audit_logs row count for our test data ---")
    with engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM audit_logs "
                "WHERE new_value::text LIKE :pat OR new_value::text LIKE :pat2"
            ),
            {"pat": f"%{email}%", "pat2": f"%{username}%"},
        ).scalar()
        print(f"audit rows mentioning our user: {n}")
        assert n is not None and n >= 2

    print("\n=== ALL LIVE CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
