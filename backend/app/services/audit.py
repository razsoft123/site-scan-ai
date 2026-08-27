import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import HttpUrl
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.audit_agent import (
    AuditWorkflowError,
    ToolExecutionRecord,
    WorkflowCallbacks,
    run_audit_workflow,
)
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
    AuditStatus,
    AuditSummary,
    CreateAudit,
    ToolExecutionResponse,
)
from app.tools.http_safety import validate_public_url


logger = logging.getLogger("uvicorn.error")


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


def _validate_public_target_url(target_url: HttpUrl) -> None:
    try:
        validate_public_url(str(target_url))
    except ValueError as exc:
        raise UnsafeAuditUrlError(str(exc)) from exc


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


def _tool_names(tool_executions: list[ToolExecution]) -> list[str]:
    names: list[str] = []
    for execution in tool_executions:
        if (
            execution.status in {"completed", "failed"}
            and execution.tool_name not in names
        ):
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
    audit = Audit(
        user_id=current_user.id,
        target_url=str(audit_data.target_url),
        instruction=audit_data.instruction,
        status=AuditStatus.QUEUED.value,
        report=None,
        overall_score=None,
        release_status=None,
    )

    try:
        db.add(audit)
        db.flush()
        logger.info(
            "audit_event=workflow_started audit_id=%s user_id=%s target_url=%s",
            audit.id,
            current_user.id,
            audit.target_url,
        )
        db.add(
            AuditEvent(
                audit_id=audit.id,
                event_type="audit_created",
                from_status=None,
                to_status=AuditStatus.QUEUED.value,
                message="Audit request validated and queued.",
                details={"agentic": True},
                sequence_number=1,
                created_at=now,
            )
        )
        transition_audit_status(
            db,
            audit,
            AuditStatus.PLANNING,
            message="Gemini is selecting deterministic tools for the audit.",
            details={"agentic": True},
        )

        def on_tools_selected(tool_names: list[str]) -> None:
            logger.info(
                "audit_event=tools_selected audit_id=%s tools=%s",
                audit.id,
                ",".join(tool_names) if tool_names else "none",
            )
            if audit.status == AuditStatus.PLANNING.value:
                transition_audit_status(
                    db,
                    audit,
                    AuditStatus.RUNNING_TOOLS,
                    event_type="tools_selected",
                    message="Gemini selected the deterministic audit tools.",
                    details={"tools": tool_names},
                )
                return
            db.add(
                AuditEvent(
                    audit_id=audit.id,
                    event_type="tools_selected",
                    from_status=None,
                    to_status=None,
                    message="Gemini selected additional deterministic tools.",
                    details={"tools": tool_names},
                    sequence_number=_next_event_sequence(db, audit.id),
                    created_at=datetime.now(timezone.utc),
                )
            )

        def on_tool_started(
            tool_name: str,
            arguments: dict[str, Any],
            sequence_number: int,
            started_at: datetime,
        ) -> None:
            logger.info(
                "audit_event=tool_started audit_id=%s sequence=%s tool=%s",
                audit.id,
                sequence_number,
                tool_name,
            )
            db.add(
                AuditEvent(
                    audit_id=audit.id,
                    event_type="tool_started",
                    from_status=None,
                    to_status=None,
                    message=f"Started {tool_name}.",
                    details={
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "tool_sequence_number": sequence_number,
                    },
                    sequence_number=_next_event_sequence(db, audit.id),
                    created_at=started_at,
                )
            )

        def on_tool_completed(record: ToolExecutionRecord) -> None:
            error_details = ";".join(
                f"{error.code}:{error.message}" for error in record.result.errors
            )
            logger.info(
                "audit_event=tool_completed audit_id=%s sequence=%s tool=%s "
                "status=%s success=%s duration_ms=%s errors=%s",
                audit.id,
                record.sequence_number,
                record.tool_name,
                record.status,
                record.result.success,
                record.result.duration_ms,
                error_details or "none",
            )
            screenshot_reference = record.result.data.get("screenshot_reference")
            if not isinstance(screenshot_reference, str):
                screenshot_reference = None
            db.add(
                ToolExecution(
                    audit_id=audit.id,
                    tool_name=record.tool_name[:100],
                    arguments=record.arguments,
                    status=record.status,
                    success=(
                        record.result.success
                        if record.status in {"completed", "failed"}
                        else None
                    ),
                    data=record.result.data,
                    errors=[
                        error.model_dump(mode="json")
                        for error in record.result.errors
                    ],
                    started_at=record.started_at,
                    completed_at=record.completed_at,
                    duration_ms=record.result.duration_ms,
                    sequence_number=record.sequence_number,
                    screenshot_reference=screenshot_reference,
                )
            )
            db.add(
                AuditEvent(
                    audit_id=audit.id,
                    event_type="tool_completed",
                    from_status=None,
                    to_status=None,
                    message=(
                        f"Completed {record.tool_name}."
                        if record.status != "rejected"
                        else f"Rejected {record.tool_name}."
                    ),
                    details={
                        "tool_name": record.tool_name,
                        "tool_sequence_number": record.sequence_number,
                        "status": record.status,
                        "success": record.result.success,
                    },
                    sequence_number=_next_event_sequence(db, audit.id),
                    created_at=record.completed_at,
                )
            )

        def on_report_started() -> None:
            logger.info(
                "audit_event=report_started audit_id=%s",
                audit.id,
            )
            if audit.status == AuditStatus.PLANNING.value:
                on_tools_selected([])
            transition_audit_status(
                db,
                audit,
                AuditStatus.GENERATING_REPORT,
                event_type="report_started",
                message="Gemini is generating the evidence-grounded report.",
                details={"agentic": True},
            )

        report = run_audit_workflow(
            target_url=str(audit_data.target_url),
            instruction=audit_data.instruction,
            callbacks=WorkflowCallbacks(
                on_tools_selected=on_tools_selected,
                on_tool_started=on_tool_started,
                on_tool_completed=on_tool_completed,
                on_report_started=on_report_started,
            ),
        )
        audit.report = report.model_dump(mode="json")
        audit.overall_score = report.overall_score
        audit.release_status = report.release_status.value
        audit.error_message = None
        transition_audit_status(
            db,
            audit,
            AuditStatus.COMPLETED,
            event_type="audit_completed",
            message="Agentic audit completed with a validated report.",
            details={"agentic": True},
        )
        db.commit()
        db.refresh(audit)
        logger.info(
            "audit_event=workflow_completed audit_id=%s status=%s "
            "duration_ms=%s release_status=%s findings=%s",
            audit.id,
            audit.status,
            audit.duration_ms,
            audit.release_status,
            len(report.findings),
        )
    except AuditWorkflowError as exc:
        logger.exception(
            "audit_event=workflow_failed audit_id=%s user_id=%s target_url=%s "
            "status=%s public_error=%s",
            getattr(audit, "id", None),
            current_user.id,
            audit.target_url,
            audit.status,
            str(exc),
        )
        audit.error_message = str(exc)
        transition_audit_status(
            db,
            audit,
            AuditStatus.FAILED,
            event_type="audit_failed",
            message="The agentic audit workflow failed.",
            details={"error": str(exc)},
        )
        try:
            db.commit()
            db.refresh(audit)
        except SQLAlchemyError as db_exc:
            logger.exception(
                "audit_event=failure_persistence_failed audit_id=%s user_id=%s",
                getattr(audit, "id", None),
                current_user.id,
            )
            db.rollback()
            raise AuditDatabaseError from db_exc
    except SQLAlchemyError as exc:
        logger.exception(
            "audit_event=database_failed audit_id=%s user_id=%s target_url=%s",
            getattr(audit, "id", None),
            current_user.id,
            audit.target_url,
        )
        db.rollback()
        raise AuditDatabaseError from exc

    try:
        tool_executions = _get_owned_tool_executions(
            db,
            current_user.id,
            [audit.id],
        )
    except SQLAlchemyError as exc:
        logger.exception(
            "audit_event=tool_execution_lookup_failed audit_id=%s user_id=%s",
            getattr(audit, "id", None),
            current_user.id,
        )
        raise AuditDatabaseError from exc
    return _audit_detail(audit, tool_executions)


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
