"""Same-transaction audit writer.

Caller passes the SQLAlchemy `Session` they're using for the data change.
We `session.add(AuditLog(...))` — caller commits. Atomic with the change.
If the surrounding transaction rolls back, the audit row rolls back too.

`request_id` accepted as `str | uuid.UUID | None`; coerced to UUID for the
DB column. Invalid strings → None (we never crash audit; never silently
drop the surrounding mutation either — the caller decides).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.models.audit import AuditLog
from app.models.enums import ActorType


def _to_uuid(request_id: str | uuid.UUID | None) -> uuid.UUID | None:
    if request_id is None:
        return None
    if isinstance(request_id, uuid.UUID):
        return request_id
    try:
        return uuid.UUID(str(request_id))
    except (ValueError, AttributeError, TypeError):
        return None


def write_audit_log(
    session: Session,
    *,
    actor_type: ActorType,
    actor_id: int | None,
    action: AuditAction,
    entity_type: str,
    entity_id: int | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    request_id: str | uuid.UUID | None = None,
) -> AuditLog:
    """Append an audit row in the caller's session.

    SAFETY: the caller is responsible for `session.commit()`. If they roll
    back, the audit row rolls back with them. Never log raw secrets,
    passwords, CSRF tokens, or session payloads via `old_value`/`new_value`.
    """
    row = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action.value,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        request_id=_to_uuid(request_id),
    )
    session.add(row)
    return row
