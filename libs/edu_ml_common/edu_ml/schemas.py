import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MlBugfixTask(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str | None = None
    difficulty: str | None = None
    topic_tags: Any = None
    task_context: str | None = None
    tests: list[str] | None = None
    expected_output: str | None = None
    input_example: str | None = None
    output_example: str | None = None
    requirements: list[str] | None = None
    constraints: list[str] | None = None
    broken_code: str | None = None


def coerce_ml_task(raw: dict[str, Any] | None) -> MlBugfixTask | None:
    if not raw:
        return None
    try:
        return MlBugfixTask.model_validate(raw)
    except Exception:
        return None


MAX_TEXT_LEN = 20_000
MAX_CODE_LEN = 200_000
MAX_TAG_LEN = 128
MAX_HINTS = 32
MAX_HINT_LEN = 2_000


class AnalyzeTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | str | None = None
    title: str = Field(..., min_length=1, max_length=MAX_TEXT_LEN)
    description: str = Field(..., min_length=1, max_length=MAX_TEXT_LEN)
    difficulty: str = Field(..., min_length=1, max_length=64)


class AnalyzeRequest(BaseModel):
    task: AnalyzeTaskInput | None = None
    task_context: str | None = Field(default=None, max_length=MAX_TEXT_LEN)
    code: str = Field(..., min_length=1, max_length=MAX_CODE_LEN)

    @field_validator("task_context")
    @classmethod
    def strip_task_context(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s if s else None

    @model_validator(mode="after")
    def task_or_legacy_context(self) -> Self:
        if self.task is None and not self.task_context:
            raise ValueError("Укажите task (id, title, description, difficulty) или task_context")
        return self


def analyze_request_storage_blob(req: AnalyzeRequest) -> str:
    if req.task is not None:
        parts: list[str] = [json.dumps(req.task.model_dump(), ensure_ascii=False)]
        if req.task_context:
            parts.append(req.task_context)
        return "\n\n".join(parts)
    return req.task_context or ""


class AnalyzeResponse(BaseModel):
    analysis: str = Field(...)
    tag_scores: dict[str, float] | None = Field(default=None)
    report: dict[str, Any] | None = Field(default=None)


class AnalyzeHealthResponse(BaseModel):
    status: str
    service: str = "code-analyze"
    model_loaded: bool
    redis_connected: bool = False
    auth_enabled: bool = False


class UserStoredEnvelope(BaseModel):
    found: bool
    data: dict[str, Any] | None = None


class UserHistoryResponse(BaseModel):
    items: list[dict[str, Any]]
    count: int
    total: int


class GenerateTaskRequest(BaseModel):
    tag1: str = Field(..., min_length=1, max_length=MAX_TAG_LEN)
    tag2: str = Field(..., min_length=1, max_length=MAX_TAG_LEN)
    tag3: str = Field(..., min_length=1, max_length=MAX_TAG_LEN)
    difficulty: Literal["easy", "medium", "hard"]
    weights: tuple[float, float, float] | None = Field(default=None)
    tests_hints: list[str] | None = Field(default=None, max_length=MAX_HINTS)
    requirements_hints: list[str] | None = Field(default=None, max_length=MAX_HINTS)
    constraints_hints: list[str] | None = Field(default=None, max_length=MAX_HINTS)

    @field_validator("weights")
    @classmethod
    def weights_nonnegative(cls, v: tuple[float, float, float] | None) -> tuple[float, float, float] | None:
        if v is None:
            return v
        if any(w < 0 for w in v):
            raise ValueError("Веса не могут быть отрицательными")
        return v

    @field_validator("tests_hints", "requirements_hints", "constraints_hints")
    @classmethod
    def trim_hint_lists(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out = [str(item).strip() for item in v if str(item).strip()]
        if any(len(item) > MAX_HINT_LEN for item in out):
            raise ValueError(f"Подсказки не должны быть длиннее {MAX_HINT_LEN} символов")
        return out


class GenerateTaskResponse(BaseModel):
    task: dict[str, Any] | None = Field(default=None)
    task_typed: MlBugfixTask | None = None
    raw_completion: str = Field(...)
    parse_ok: bool


class GenerateHealthResponse(BaseModel):
    status: str
    service: str = "task-generate"
    model_loaded: bool
    redis_connected: bool = False
    auth_enabled: bool = False


class UserProfilePut(BaseModel):
    model_config = ConfigDict(extra="allow")
    weak_tags: list[str] | None = None
    tags: list[str] | None = None
    all_tags_used: list[str] | None = None

    @field_validator("weak_tags", "tags", "all_tags_used", mode="before")
    @classmethod
    def strip_tag_lists(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("Ожидается массив строк")
        out = [str(t).strip() for t in v if t is not None and str(t).strip()]
        return out[:512]


class TagStatsSample(BaseModel):
    sum: float = Field(..., ge=0)
    count: int = Field(..., ge=0)


class StudentProfileContract(BaseModel):
    id: str = Field(..., min_length=1)
    weak_tags: list[str] = Field(default_factory=list)
    tag_stats: dict[str, TagStatsSample] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: str | float | None = None


class UserProgressPut(BaseModel):
    weak_tags: list[str] = Field(..., min_length=1, max_length=32)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    weights: tuple[float, float, float] | None = Field(default=None)
    tests_hints: list[str] | None = Field(default=None, max_length=MAX_HINTS)
    requirements_hints: list[str] | None = Field(default=None, max_length=MAX_HINTS)
    constraints_hints: list[str] | None = Field(default=None, max_length=MAX_HINTS)

    @field_validator("weak_tags", mode="before")
    @classmethod
    def strip_tags(cls, v: list[str]) -> list[str]:
        if not v:
            return v
        out = [str(t).strip() for t in v if t is not None and str(t).strip()]
        if not out:
            raise ValueError("Нужен хотя бы один непустой тег")
        return out[:32]

    @field_validator("weights")
    @classmethod
    def weights_nonnegative_put(cls, v: tuple[float, float, float] | None) -> tuple[float, float, float] | None:
        if v is None:
            return v
        if any(w < 0 for w in v):
            raise ValueError("Веса не могут быть отрицательными")
        return v

    @field_validator("tests_hints", "requirements_hints", "constraints_hints")
    @classmethod
    def trim_hint_lists_put(cls, v: list[str] | None) -> list[str] | None:
        return GenerateTaskRequest.trim_hint_lists(v)


class GenerateFromProgressRequest(BaseModel):
    difficulty_override: Literal["easy", "medium", "hard"] | None = Field(default=None)


class GenerateFromProgressResponse(BaseModel):
    task: dict[str, Any] | None = None
    task_typed: MlBugfixTask | None = None
    raw_completion: str
    parse_ok: bool
    used_weak_tags: tuple[str, str, str]
    difficulty_used: Literal["easy", "medium", "hard"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class QueuedJobAccepted(BaseModel):
    job_id: str
    status: Literal["queued"] = "queued"


class AsyncJobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "processing", "completed", "failed", "unknown"]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
