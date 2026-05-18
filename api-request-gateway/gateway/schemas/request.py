from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

Difficulty = Literal["easy", "medium", "hard"]


class AnalyzeIn(BaseModel):
    student_id: str = Field(..., min_length=1, description="External student identifier (UUID string)")
    task_description: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    webhook_url: HttpUrl


class GenerateIn(BaseModel):
    student_id: str = Field(..., min_length=1)
    tags: list[str] = Field(..., min_length=1)
    difficulty: Difficulty
    webhook_url: HttpUrl


class PipelineIn(BaseModel):
    student_id: str = Field(..., min_length=1)
    task_description: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    webhook_url: HttpUrl
