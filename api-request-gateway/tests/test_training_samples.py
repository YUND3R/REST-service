from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "libs" / "edu_ml_common"))

from edu_ml.schemas import MlBugfixTask  # noqa: E402


def _load_sample(name: str) -> list[dict[str, Any]]:
    raw = json.loads((REPO_ROOT / name).read_text(encoding="utf-8-sig"))
    assert isinstance(raw, list)
    assert raw
    return raw


class AnalyzeTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    weight: float = Field(..., ge=0)


class AnalyzeTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | str | None = None
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    difficulty: str = Field(..., min_length=1)
    tags: list[AnalyzeTag] = Field(..., min_length=1)


class SolutionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str = Field(..., min_length=1)
    success: bool


class AlignmentScore(BaseModel):
    model_config = ConfigDict(extra="allow")

    required_weight: float = Field(..., ge=0)
    applied: bool | Literal["partially"]
    score: int | float = Field(..., ge=0, le=10)
    evidence: str = Field(..., min_length=1)


class TaskCompliance(BaseModel):
    model_config = ConfigDict(extra="allow")

    is_relevant: bool | Literal["partially"]
    score: int | float = Field(..., ge=0, le=10)
    description: str = Field(..., min_length=1)
    tag_alignment: dict[str, AlignmentScore] = Field(..., min_length=1)
    missing_requirements: list[str] = Field(default_factory=list)


class Correctness(BaseModel):
    model_config = ConfigDict(extra="allow")

    is_correct: bool | Literal["partially"]
    score: int | float = Field(..., ge=0, le=10)


class AnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str = Field(..., min_length=1)
    task_compliance: TaskCompliance
    code_quality_score: int | float = Field(..., ge=0, le=10)
    correctness: Correctness
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    detailed_analysis: str = Field(..., min_length=1)


class AnalyzeSolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solution: SolutionPayload
    analysis: AnalysisPayload


class AnalyzeTrainingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: AnalyzeTask
    solutions: list[AnalyzeSolution] = Field(..., min_length=1)


def test_broken_code_generator_training_samples_validate() -> None:
    for item in _load_sample("BROKEN CODE generator.json"):
        task = MlBugfixTask.model_validate(item)
        assert task.title
        assert task.difficulty in {"easy", "medium", "hard"}
        assert task.task_context
        assert task.tests
        assert task.requirements
        assert task.constraints
        assert task.broken_code and "ВОТ ТУТ НУЖНО ИСПРАВИТЬ КОД" in task.broken_code


def test_code_analyze_training_samples_validate() -> None:
    for item in _load_sample("CODE ANALYZE.json"):
        record = AnalyzeTrainingRecord.model_validate(item)
        task_tags = {tag.name for tag in record.task.tags}
        assert task_tags
        for solution in record.solutions:
            alignment_tags = set(solution.analysis.task_compliance.tag_alignment)
            assert task_tags <= alignment_tags
