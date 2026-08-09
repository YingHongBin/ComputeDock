from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .models import AuditEvent, User
from .security import utcnow


def record_audit(
    db: Session,
    actor: User | None,
    action: str,
    object_type: str,
    object_id: uuid.UUID | str,
    *,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=uuid.uuid4(),
        actor_id=actor.id if actor else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        before=before,
        after=after,
        created_at=utcnow(),
    )
    db.add(event)
    return event
