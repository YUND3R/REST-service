from typing import Any

from pydantic import BaseModel, ConfigDict


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
