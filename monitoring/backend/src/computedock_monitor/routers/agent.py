from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from ..auth import parse_bearer
from ..database import get_db
from ..schemas import SampleAccepted, SampleInput
from ..services import authenticate_reporting_token, ingest_sample

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post("/samples", response_model=SampleAccepted)
def upload_samples(
    payload: SampleInput,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> SampleAccepted:
    token = parse_bearer(authorization)
    resource, request = authenticate_reporting_token(db, token)
    result, container = ingest_sample(db, resource, payload, request)
    return SampleAccepted(status=result, container_id=container.id)  # type: ignore[arg-type]
