from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

StatusLiteral = Literal["pending", "processing", "done", "failed"]


class TaskAccepted(BaseModel):
    task_id: str
    status: Literal["pending"] = "pending"


class WeakSpot(BaseModel):
    line: int | None = None
    issue: str | None = None
    hint: str | None = None


class AnalysisBlock(BaseModel):
    score: int = Field(..., ge=1, le=10)
    weak_spots: list[dict[str, Any] | WeakSpot] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class GeneratedTaskBlock(BaseModel):
    title: str = ""
    difficulty: str = "medium"
    topic_tags: dict[str, Any] = Field(default_factory=dict)
    task_context: str = ""
    tests: list[Any] = Field(default_factory=list)
    broken_code: str = ""


class TaskStatusResponse(BaseModel):
    task_id: str
    status: StatusLiteral
    error: str | None = None
    result: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    detail: str
