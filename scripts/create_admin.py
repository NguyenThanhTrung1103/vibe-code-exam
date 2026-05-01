"""CLI: bootstrap the first admin user.

Usage:
    uv run python -m scripts.create_admin --email admin@example.com --username admin
    # password prompted interactively, or pass via EXAM_ADMIN_PW env var.

Idempotent: if a user with that email already exists, exits non-zero with a
message — refuses to overwrite an existing user.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.auth.service import (
    get_user_by_email,
    get_user_by_username,
    hash_password,
)
from app.db import SessionLocal
from app.models.enums import ActorType, UserRole
from app.models.users import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first admin user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--password",
        default=None,
        help="If omitted, read from EXAM_ADMIN_PW env or prompt interactively.",
    )
    args = parser.parse_args()

    pw = args.password or os.environ.get("EXAM_ADMIN_PW")
    if not pw:
        pw = getpass.getpass("Admin password (≥12 chars): ")
    if len(pw) < 12:
        print("ERROR: password must be at least 12 characters.", file=sys.stderr)
        return 2

    email = args.email.strip().lower()
    username = args.username.strip().lower()

    with SessionLocal() as session:
        if get_user_by_email(session, email) is not None:
            print(f"ERROR: a user with email {email!r} already exists.", file=sys.stderr)
            return 3
        if get_user_by_username(session, username) is not None:
            print(f"ERROR: a user with username {username!r} already exists.", file=sys.stderr)
            return 3

        user = User(
            email=email,
            username=username,
            password_hash=hash_password(pw),
            role=UserRole.admin,
        )
        session.add(user)
        session.flush()
        # Snapshot id BEFORE commit/detach so the post-with-block print works.
        new_user_id = user.id

        write_audit_log(
            session,
            actor_type=ActorType.system,
            actor_id=None,
            action=AuditAction.USER_REGISTERED,
            entity_type="user",
            entity_id=new_user_id,
            new_value={"email": email, "username": username, "role": "admin"},
            reason="bootstrap-cli",
        )

        session.commit()

    # Don't print the password back. Done.
    print(f"OK: admin user created (id={new_user_id}, email={email}, username={username}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
