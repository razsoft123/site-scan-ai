from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.schemas.audit import (
    AuditDetail,
    AuditEventResponse,
    AuditSummary,
    CreateAudit,
)
from app.services.audit import (
    create_audit as create_audit_service,
    get_audit as get_audit_service,
    get_audit_events as get_audit_events_service,
    list_audits as list_audits_service,
)
from app.services.auth import get_current_user

router = APIRouter(prefix="/audits", tags=["audits"])


@router.post("", response_model=AuditDetail, status_code=status.HTTP_201_CREATED)
def create_audit(
    audit_data: CreateAudit,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AuditDetail:
    return create_audit_service(db, current_user, audit_data)


@router.get("", response_model=list[AuditSummary])
def get_audits(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditSummary]:
    return list_audits_service(
        db,
        current_user,
        limit=limit,
        offset=offset,
    )


@router.get("/{audit_id}", response_model=AuditDetail)
def get_audit(
    audit_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AuditDetail:
    return get_audit_service(db, current_user, audit_id)


@router.get("/{audit_id}/events", response_model=list[AuditEventResponse])
def get_events(
    audit_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AuditEventResponse]:
    return get_audit_events_service(db, current_user, audit_id)

