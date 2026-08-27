from typing import Any

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    code: str
    message: str


class ToolResult(BaseModel):
    tool: str
    success: bool
    duration_ms: int = Field(ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
    errors: list[ToolError] = Field(default_factory=list)
