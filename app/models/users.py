"""Identity — `users` table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True, create_type=True),
        nullable=False,
    )
    # Phase 03: tracks last password input/change for admin re-prompt at 24h.
    # NULL means "never", treated as "needs re-prompt" by the auth layer.
    last_password_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
