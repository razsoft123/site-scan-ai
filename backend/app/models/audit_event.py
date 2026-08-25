from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('audit_created', 'status_changed', "
            "'tools_selected', 'tool_started', 'tool_completed', "
            "'report_started', 'audit_completed', 'audit_failed')",
            name="ck_audit_event_event_type",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('queued', 'planning', 'running_tools', "
            "'generating_report', 'completed', 'failed')",
            name="ck_audit_event_from_status",
        ),
        CheckConstraint(
            "to_status IS NULL OR to_status IN "
            "('queued', 'planning', 'running_tools', "
            "'generating_report', 'completed', 'failed')",
            name="ck_audit_event_to_status",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="ck_audit_event_sequence_number",
        ),
        UniqueConstraint(
            "audit_id",
            "sequence_number",
            name="uq_audit_event_audit_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("audit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
