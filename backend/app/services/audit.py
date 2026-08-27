from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any

from pydantic import HttpUrl
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions.audit import (
    AuditDatabaseError,
    AuditNotFoundError,
    InvalidAuditTransitionError,
    UnsafeAuditUrlError,
)
from app.models.audit import Audit
from app.models.audit_event import AuditEvent
from app.models.tool_execution import ToolExecution
from app.models.user import User
from app.schemas.audit import (
    AuditDetail,
    AuditEventResponse,
    AuditReport,
    AuditStatus,
    AuditSummary,
    CreateAudit,
    ReleaseStatus,
    ToolExecutionResponse,
)


VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    AuditStatus.QUEUED.value: {
        AuditStatus.PLANNING.value,
        AuditStatus.FAILED.value,
    },
    AuditStatus.PLANNING.value: {
        AuditStatus.RUNNING_TOOLS.value,
        AuditStatus.FAILED.value,
    },
    AuditStatus.RUNNING_TOOLS.value: {
        AuditStatus.GENERATING_REPORT.value,
        AuditStatus.FAILED.value,
    },
    AuditStatus.GENERATING_REPORT.value: {
        AuditStatus.COMPLETED.value,
        AuditStatus.FAILED.value,
    },
    AuditStatus.COMPLETED.value: set(),
    AuditStatus.FAILED.value: set(),
}

BLOCKED_HOST_SUFFIXES = (
    ".internal",
    ".lan",
    ".local",
    ".localhost",
)


def _validate_public_target_url(target_url: HttpUrl) -> None:
    if target_url.username is not None or target_url.password is not None:
        raise UnsafeAuditUrlError("URLs containing credentials cannot be scanned.")

    hostname = target_url.host
    if hostname is None:
        raise UnsafeAuditUrlError("The target URL must contain a hostname.")

    hostname = hostname.lower().rstrip(".")
    if (
        hostname == "localhost"
        or hostname.endswith(BLOCKED_HOST_SUFFIXES)
        or ("." not in hostname and ":" not in hostname)
    ):
        raise UnsafeAuditUrlError("Local and internal hostnames cannot be scanned.")

    address_text = (
        hostname[1:-1]
        if hostname.startswith("[") and hostname.endswith("]")
        else hostname
    )
    try:
        address = ip_address(address_text)
    except ValueError:
        return

    if not address.is_global:
        raise UnsafeAuditUrlError("Private and non-public IP addresses cannot be scanned.")


def _next_event_sequence(db: Session, audit_id: int) -> int:
    current_sequence = db.scalar(
        select(func.coalesce(func.max(AuditEvent.sequence_number), 0)).where(
            AuditEvent.audit_id == audit_id
        )
    )
    return int(current_sequence or 0) + 1


def transition_audit_status(
    db: Session,
    audit: Audit,
    new_status: AuditStatus,
    *,
    message: str,
    event_type: str = "status_changed",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    current_status = audit.status
    target_status = new_status.value
    allowed_statuses = VALID_STATUS_TRANSITIONS.get(current_status, set())

    if target_status not in allowed_statuses:
        raise InvalidAuditTransitionError(
            f"Cannot transition an audit from '{current_status}' to '{target_status}'."
        )

    now = datetime.now(timezone.utc)
    if target_status == AuditStatus.PLANNING.value and audit.started_at is None:
        audit.started_at = now
    if target_status in {AuditStatus.COMPLETED.value, AuditStatus.FAILED.value}:
        audit.completed_at = now
        if audit.started_at is not None:
            audit.duration_ms = max(
                0,
                int((now - audit.started_at).total_seconds() * 1000),
            )

    audit.status = target_status
    audit.updated_at = now
    event = AuditEvent(
        audit_id=audit.id,
        event_type=event_type,
        from_status=current_status,
        to_status=target_status,
        message=message,
        details=details,
        sequence_number=_next_event_sequence(db, audit.id),
        created_at=now,
    )
    db.add(event)
    return event


def _mock_report(generated_at: datetime) -> AuditReport:
    return AuditReport(
        overall_score=None,
        release_status=ReleaseStatus.UNKNOWN,
        executive_summary=(
            "This is a mock report. No diagnostic tools have run yet, so no "
            "evidence-based findings or score were generated."
        ),
        findings=[],
        screenshot_reference=None,
        generated_at=generated_at,
        schema_version="1.0",
        is_mock=True,
    )


def _tool_names(tool_executions: list[ToolExecution]) -> list[str]:
    names: list[str] = []
    for execution in tool_executions:
        if execution.tool_name not in names:
            names.append(execution.tool_name)
    return names


def _audit_summary(
    audit: Audit,
    tool_executions: list[ToolExecution],
) -> AuditSummary:
    summary = AuditSummary.model_validate(audit)
    return summary.model_copy(update={"tools_executed": _tool_names(tool_executions)})


def _audit_detail(
    audit: Audit,
    tool_executions: list[ToolExecution],
) -> AuditDetail:
    detail = AuditDetail.model_validate(audit)
    return detail.model_copy(
        update={
            "tools_executed": _tool_names(tool_executions),
            "tool_executions": [
                ToolExecutionResponse.model_validate(execution)
                for execution in tool_executions
            ],
        }
    )


def create_audit(
    db: Session,
    current_user: User,
    audit_data: CreateAudit,
) -> AuditDetail:
    _validate_public_target_url(audit_data.target_url)
    now = datetime.now(timezone.utc)
    report = _mock_report(now)
    audit = Audit(
        user_id=current_user.id,
        target_url=str(audit_data.target_url),
        instruction=audit_data.instruction,
        status=AuditStatus.QUEUED.value,
        report=report.model_dump(mode="json"),
        overall_score=report.overall_score,
        release_status=report.release_status.value,
    )

    try:
        db.add(audit)
        db.flush()
        db.add(
            AuditEvent(
                audit_id=audit.id,
                event_type="audit_created",
                from_status=None,
                to_status=AuditStatus.QUEUED.value,
                message="Audit request validated and queued.",
                details={"mock": True},
                sequence_number=1,
                created_at=now,
            )
        )
        transition_audit_status(
            db,
            audit,
            AuditStatus.PLANNING,
            message="Preparing the mock audit plan.",
            details={"mock": True},
        )
        transition_audit_status(
            db,
            audit,
            AuditStatus.RUNNING_TOOLS,
            message="Mock tool execution stage completed without running tools.",
            details={"mock": True, "tools": []},
        )
        transition_audit_status(
            db,
            audit,
            AuditStatus.GENERATING_REPORT,
            event_type="report_started",
            message="Generating the mock report.",
            details={"mock": True},
        )
        transition_audit_status(
            db,
            audit,
            AuditStatus.COMPLETED,
            event_type="audit_completed",
            message="Mock audit completed.",
            details={"mock": True},
        )
        db.commit()
        db.refresh(audit)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AuditDatabaseError from exc

    return _audit_detail(audit, [])


def _get_owned_audit(db: Session, user_id: int, audit_id: int) -> Audit:
    try:
        audit = db.scalar(
            select(Audit).where(
                Audit.id == audit_id,
                Audit.user_id == user_id,
            )
        )
    except SQLAlchemyError as exc:
        raise AuditDatabaseError from exc

    if audit is None:
        raise AuditNotFoundError
    return audit


def _get_owned_tool_executions(
    db: Session,
    user_id: int,
    audit_ids: list[int],
) -> list[ToolExecution]:
    if not audit_ids:
        return []

    return list(
        db.scalars(
            select(ToolExecution)
            .join(Audit, ToolExecution.audit_id == Audit.id)
            .where(
                Audit.user_id == user_id,
                Audit.id.in_(audit_ids),
            )
            .order_by(ToolExecution.audit_id, ToolExecution.sequence_number)
        ).all()
    )


def list_audits(
    db: Session,
    current_user: User,
    *,
    limit: int,
    offset: int,
) -> list[AuditSummary]:
    try:
        audits = list(
            db.scalars(
                select(Audit)
                .where(Audit.user_id == current_user.id)
                .order_by(Audit.created_at.desc(), Audit.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
        tool_executions = _get_owned_tool_executions(
            db,
            current_user.id,
            [audit.id for audit in audits],
        )
    except SQLAlchemyError as exc:
        raise AuditDatabaseError from exc

    tools_by_audit: dict[int, list[ToolExecution]] = {
        audit.id: [] for audit in audits
    }
    for execution in tool_executions:
        tools_by_audit[execution.audit_id].append(execution)

    return [
        _audit_summary(audit, tools_by_audit[audit.id])
        for audit in audits
    ]


def get_audit(
    db: Session,
    current_user: User,
    audit_id: int,
) -> AuditDetail:
    audit = _get_owned_audit(db, current_user.id, audit_id)

    try:
        tool_executions = _get_owned_tool_executions(
            db,
            current_user.id,
            [audit.id],
        )
    except SQLAlchemyError as exc:
        raise AuditDatabaseError from exc

    return _audit_detail(audit, tool_executions)


def get_audit_events(
    db: Session,
    current_user: User,
    audit_id: int,
) -> list[AuditEventResponse]:
    _get_owned_audit(db, current_user.id, audit_id)

    try:
        events = list(
            db.scalars(
                select(AuditEvent)
                .join(Audit, AuditEvent.audit_id == Audit.id)
                .where(
                    AuditEvent.audit_id == audit_id,
                    Audit.user_id == current_user.id,
                )
                .order_by(AuditEvent.sequence_number)
            ).all()
        )
    except SQLAlchemyError as exc:
        raise AuditDatabaseError from exc

    return [AuditEventResponse.model_validate(event) for event in events]
