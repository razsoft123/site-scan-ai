from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class AuditStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING_TOOLS = "running_tools"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
    FAILED = "failed"


class ReleaseStatus(str, Enum):
    READY = "ready"
    NEEDS_ATTENTION = "needs_attention"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class FindingCategory(str, Enum):
    SEO = "SEO"
    SECURITY = "Security"
    RELIABILITY = "Reliability"
    ACCESSIBILITY = "Accessibility"
    BROWSER = "Browser"


class FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CreateAudit(BaseModel):
    target_url: HttpUrl
    instruction: str = Field(min_length=3, max_length=2000)

    @field_validator("instruction", mode="before")
    @classmethod
    def strip_instruction(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AuditFinding(BaseModel):
    id: str
    category: FindingCategory
    severity: FindingSeverity
    title: str
    description: str
    evidence: dict[str, Any] = Field(min_length=1)
    recommended_fix: str
    source_tool: Literal[
        "inspect_metadata",
        "inspect_security_headers",
        "check_broken_links",
        "inspect_browser",
    ]
    is_release_blocker: bool = False


class AuditReport(BaseModel):
    overall_score: int | None = Field(default=None, ge=0, le=100)
    release_status: ReleaseStatus
    executive_summary: str
    findings: list[AuditFinding] = Field(default_factory=list)
    screenshot_reference: str | None = None
    generated_at: datetime
    schema_version: str = "1.0"
    is_mock: bool = False


class ToolErrorResponse(BaseModel):
    code: str
    message: str


class ToolExecutionResponse(BaseModel):
    id: int
    tool_name: str
    arguments: dict[str, Any]
    status: str
    success: bool | None
    data: dict[str, Any]
    errors: list[ToolErrorResponse]
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    sequence_number: int
    screenshot_reference: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditSummary(BaseModel):
    id: int
    target_url: HttpUrl
    instruction: str
    status: AuditStatus
    overall_score: int | None
    release_status: ReleaseStatus | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    updated_at: datetime
    tools_executed: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AuditDetail(AuditSummary):
    report: AuditReport | None
    tool_executions: list[ToolExecutionResponse] = Field(default_factory=list)


class AuditEventResponse(BaseModel):
    id: int
    event_type: str
    from_status: AuditStatus | None
    to_status: AuditStatus | None
    message: str
    details: dict[str, Any] | None
    sequence_number: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
