"""Shared FastAPI dependencies.

Re-exports `get_session` from `app.db` so routers don't import the engine
module directly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from redis import Redis
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.redis_client import get_redis


def get_redis_dep() -> Redis:
    return get_redis()


SessionDep = Annotated[Session, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis_dep)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

__all__ = [
    "RedisDep",
    "SessionDep",
    "SettingsDep",
    "get_redis_dep",
    "get_session",
    "get_settings",
]
