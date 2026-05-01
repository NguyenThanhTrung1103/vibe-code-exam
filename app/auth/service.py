"""Password hashing + user authentication primitives.

Argon2id via passlib's CryptContext. The context handles both the canonical
hash format and rehash-on-verify when params drift in the future.
"""

from __future__ import annotations

from datetime import UTC, datetime

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.models.enums import ActorType, UserRole
from app.models.users import User

# argon2id with passlib's tuned defaults (~50 ms on modern CPU).
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        # Treat any malformed-hash error as a verification failure — never
        # leak which case it was.
        return False


def needs_rehash(hashed: str) -> bool:
    return _pwd_context.needs_update(hashed)


def get_user_by_email(session: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == email.strip().lower())
    return session.scalars(stmt).one_or_none()


def get_user_by_username(session: Session, username: str) -> User | None:
    stmt = select(User).where(User.username == username.strip().lower())
    return session.scalars(stmt).one_or_none()


def get_user(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def register_user(
    session: Session,
    *,
    email: str,
    username: str,
    password: str,
    role: UserRole,
    request_id: str | None = None,
) -> User:
    """Create a user + audit row in the same transaction.

    Caller is responsible for committing. If the audit write fails, the
    surrounding transaction must roll back — there is no fire-and-forget.
    """
    now = datetime.now(UTC)
    user = User(
        email=email.strip().lower(),
        username=username.strip().lower(),
        password_hash=hash_password(password),
        role=role,
        last_password_at=now,
    )
    session.add(user)
    session.flush()  # populate user.id
    write_audit_log(
        session,
        actor_type=ActorType.system if role == UserRole.admin else ActorType.user,
        actor_id=user.id,
        action=AuditAction.USER_REGISTERED,
        entity_type="user",
        entity_id=user.id,
        new_value={"email": user.email, "username": user.username, "role": user.role.value},
        request_id=request_id,
    )
    return user


def authenticate(session: Session, *, identifier: str, password: str) -> User | None:
    """Return the user if credentials match, else None.

    `identifier` is matched as either email or username (case-insensitive).
    Always runs argon2 verify even on a missing user to keep timing
    constant — defends against username enumeration via timing.
    """
    ident = identifier.strip().lower()
    user = get_user_by_email(session, ident) or get_user_by_username(session, ident)
    if user is None:
        # Constant-time decoy verify so existence-check timing matches.
        _pwd_context.dummy_verify()
        return None
    if not verify_password(password, user.password_hash):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        # last_password_at unchanged — they typed the same password.
    return user
