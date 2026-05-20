from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import torch
from edu_ml.jsonutil import extract_json_object
from transformers import AutoModelForCausalLM, AutoTokenizer

from task_svc.settings_generate import GenerateServiceSettings, get_generate_settings

logger = logging.getLogger(__name__)
SYSTEM_PROMPT = (
    "Ты генерируешь новую ML bugfix-задачу строго в формате объектов из датасета. "
    "Верни только один JSON-объект без Markdown и без пояснений. "
    "Порядок полей должен быть ровно таким: "
    "`title`, `difficulty`, `topic_tags`, `task_context`, `tests`, "
    "`expected_output`, `input_example`, `output_example`, `requirements`, "
    "`constraints`, `broken_code`. "
    "`tests`, `requirements` и `constraints` должны быть массивами строк. "
    "`broken_code` должен быть одной строкой с полным Python-кодом и символами `\\n`. "
    "Не добавляй лишние поля и не обрывай JSON."
)


def _pick_dtype() -> torch.dtype:
    if torch.cuda.is_available():
        if torch.cuda.is_bf16_supported():
            return torch.bfloat16
        return torch.float16
    return torch.float32


def _infer_device(model: Any) -> torch.device:
    return next(model.parameters()).device


def _load_causal_lm(local_dir: str) -> tuple[Any, Any]:
    dtype = _pick_dtype()
    tokenizer = AutoTokenizer.from_pretrained(local_dir, local_files_only=True, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        local_dir, torch_dtype=dtype, device_map="auto", trust_remote_code=True, local_files_only=True
    )
    return (tokenizer, model)


@dataclass
class GenerateRuntime:
    settings: GenerateServiceSettings = field(default_factory=get_generate_settings)
    tokenizer: Any | None = None
    model: Any | None = None


runtime = GenerateRuntime()


def ensure_model_loaded() -> None:
    if runtime.model is None:
        path = runtime.settings.local_model_path
        logger.info("Loading task-generate model from local path: %s", path)
        tok, mdl = _load_causal_lm(path)
        runtime.tokenizer = tok
        runtime.model = mdl


def preload_model() -> None:
    ensure_model_loaded()


def _normalize_weights(w: tuple[float, float, float] | None, tags: tuple[str, str, str]) -> dict[str, float]:
    if w is None:
        v = 1.0 / 3.0
        return {tags[0]: v, tags[1]: v, tags[2]: v}
    a, b, c = w
    s = a + b + c
    if s <= 0:
        v = 1.0 / 3.0
        return {tags[0]: v, tags[1]: v, tags[2]: v}
    return {tags[0]: a / s, tags[1]: b / s, tags[2]: c / s}


def generate_broken_task(
    *,
    tag1: str,
    tag2: str,
    tag3: str,
    difficulty: str,
    weights: tuple[float, float, float] | None,
    tests_hints: list[str] | None = None,
    requirements_hints: list[str] | None = None,
    constraints_hints: list[str] | None = None,
) -> tuple[str, dict[str, Any] | None, bool]:
    ensure_model_loaded()
    assert runtime.tokenizer is not None and runtime.model is not None
    tags = (tag1, tag2, tag3)
    topic_tags = _normalize_weights(weights, tags)
    payload = {"difficulty": difficulty, "topic_tags": topic_tags}
    parts = [
        "Сгенерируй новую ML bugfix-задачу по параметрам ниже. "
        "В `broken_code` оставь ошибки и при необходимости маркер `ВОТ ТУТ НУЖНО ИСПРАВИТЬ КОД`.\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    ]
    hint_lines: list[str] = []
    if tests_hints:
        hint_lines.append("Учти пожелания к массиву tests (строки проверок): " + "; ".join(tests_hints))
    if requirements_hints:
        hint_lines.append("Учти пожелания к requirements: " + "; ".join(requirements_hints))
    if constraints_hints:
        hint_lines.append("Учти пожелания к constraints: " + "; ".join(constraints_hints))
    if hint_lines:
        parts.append("\n".join(hint_lines))
    task_spec = "\n\n".join(parts)
    prompt = f"{SYSTEM_PROMPT}\n\n{task_spec}"
    device = _infer_device(runtime.model)
    inputs = runtime.tokenizer(prompt, return_tensors="pt").to(device)
    prompt_length = inputs["input_ids"].shape[1]
    with torch.no_grad():
        out = runtime.model.generate(
            **inputs,
            max_new_tokens=runtime.settings.max_new_tokens,
            temperature=runtime.settings.temperature,
            top_p=runtime.settings.top_p,
            do_sample=True,
            pad_token_id=runtime.tokenizer.pad_token_id,
            eos_token_id=runtime.tokenizer.eos_token_id,
        )
    completion_tokens = out[0][prompt_length:]
    raw = runtime.tokenizer.decode(completion_tokens, skip_special_tokens=True).strip()
    try:
        task = extract_json_object(raw)
        return (raw, task, True)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("JSON parse failed: %s", e)
        return (raw, None, False)
