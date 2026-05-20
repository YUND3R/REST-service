from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import torch
from edu_ml.schemas import AnalyzeTaskInput
from edu_ml.tag_report import extract_tag_mastery_from_report
from edu_ml.tag_stats import clamp_tag_score
from transformers import AutoModelForCausalLM, AutoTokenizer

from analyze_svc.settings_analyze import AnalyzeServiceSettings, get_analyze_settings

logger = logging.getLogger(__name__)


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
class AnalyzeRuntime:
    settings: AnalyzeServiceSettings = field(default_factory=get_analyze_settings)
    tokenizer: Any | None = None
    model: Any | None = None


runtime = AnalyzeRuntime()
EDU_REPORT_JSON = "EDU_REPORT_JSON:"
LEGACY_TAG_SCORES = "EDU_TAG_SCORES_JSON:"


@dataclass
class AnalyzeResult:
    analysis: str
    tag_scores: dict[str, float]
    report_json: dict[str, Any] | None = None
    raw_completion: str = ""


def ensure_model_loaded() -> None:
    if runtime.model is None:
        path = runtime.settings.local_model_path
        logger.info("Loading code-analyze model from local path: %s", path)
        tok, mdl = _load_causal_lm(path)
        runtime.tokenizer = tok
        runtime.model = mdl


def preload_model() -> None:
    ensure_model_loaded()


def _extract_braced_object(tail: str) -> dict[str, Any] | None:
    m = re.search("\\{", tail)
    if not m:
        return None
    start = m.start()
    depth = 0
    end = -1
    for i, c in enumerate(tail[start:], start=start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    try:
        raw = json.loads(tail[start:end])
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def _extract_summary_from_report(report: dict[str, Any]) -> str | None:
    sols = report.get("solutions")
    if isinstance(sols, list):
        for sol in sols:
            if not isinstance(sol, dict):
                continue
            an = sol.get("analysis")
            if not isinstance(an, dict):
                continue
            s = an.get("summary")
            if isinstance(s, str) and s.strip():
                return s.strip()
        for sol in sols:
            if not isinstance(sol, dict):
                continue
            an = sol.get("analysis")
            if not isinstance(an, dict):
                continue
            s = an.get("detailed_analysis")
            if isinstance(s, str) and s.strip():
                return s.strip()
    for key in ("summary", "analysis"):
        s = report.get(key)
        if isinstance(s, str) and s.strip():
            return s.strip()
    return None


def _parse_legacy_flat_scores(tail: str) -> dict[str, float]:
    obj = _extract_braced_object(tail)
    if not obj:
        return {}
    out: dict[str, float] = {}
    for k, v in obj.items():
        if not isinstance(k, str) or not k.strip():
            continue
        c = clamp_tag_score(v)
        if c is not None:
            out[k.strip()] = c
    return out


def _inject_client_task(report: dict[str, Any], task: AnalyzeTaskInput) -> None:
    inner = report.get("task")
    if not isinstance(inner, dict):
        inner = {}
    inner["id"] = task.id
    inner["title"] = task.title
    inner["description"] = task.description
    inner["difficulty"] = task.difficulty
    report["task"] = inner


def parse_model_completion(completion: str) -> AnalyzeResult:
    raw = completion.strip()
    idx = raw.rfind(EDU_REPORT_JSON)
    if idx >= 0:
        tail = raw[idx + len(EDU_REPORT_JSON) :].strip()
        report = _extract_braced_object(tail)
        if report is not None:
            summary = _extract_summary_from_report(report) or raw[:idx].strip()
            tags = extract_tag_mastery_from_report(report)
            return AnalyzeResult(analysis=summary.strip(), tag_scores=tags, report_json=report)
    idx2 = raw.rfind(LEGACY_TAG_SCORES)
    if idx2 >= 0:
        tail = raw[idx2 + len(LEGACY_TAG_SCORES) :].strip()
        scores = _parse_legacy_flat_scores(tail)
        head = raw[:idx2].strip()
        legacy_report: dict[str, Any] = {"summary": head, "tag_mastery": scores}
        return AnalyzeResult(
            analysis=head or raw, tag_scores=scores, report_json=legacy_report if scores or head else None
        )
    return AnalyzeResult(analysis=raw, tag_scores={}, report_json=None)


def _schema_block() -> str:
    return (
        '{\n  "task": {"id": null, "title": "…", "description": "…", '
        '"difficulty": "…", "tags": [{"name": "тег", "weight": 0.5}]},\n'
        '  "solutions": [{\n    "solution": {"code": "<код ученика>", "success": true},\n'
        "    \"analysis\": { ... }\n  }]\n}"
    )


def _analyze_prompt_lines_legacy(task_context: str, code: str) -> list[str]:
    schema = "\n".join(
        [
            '{',
            '  "task": {"id": null, "title": "строка", "description": "строка",',
            '           "difficulty": "easy|medium|hard", "tags": [{"name": "тег", "weight": 0.5}]},',
            '  "solutions": [{',
            '    "solution": {"code": "<тот же код ученика>", "success": true},',
            '    "analysis": {',
            '      "summary": "краткое резюме для ученика",',
            '      "task_compliance": {',
            '        "is_relevant": true, "score": 8, "description": "строка",',
            '        "tag_alignment": {"ИмяТегаИзУсловия": {"required_weight": 0.5,',
            '          "applied": true, "score": 8, "evidence": "текст"}},',
            '        "missing_requirements": [], "extra_features": []',
            '      },',
            '      "code_quality_score": 8.0,',
            '      "correctness": {"is_correct": true, "score": 8, "edge_cases_handled": true},',
            '      "strengths": [], "weaknesses": [], "recommendations": [],',
            '      "detailed_analysis": "развёрнутый разбор",',
            '      "Временная сложность решения": {"time_complexity": "O(...)", "space_complexity": "O(...)"}',
            "    }",
            "  }]",
            "}",
        ]
    )
    tail_instr = (
        "После произвольного текстового разбора в конце ответа выведи ровно одну финальную строку: префикс "
        + EDU_REPORT_JSON
        + " сразу затем один валидный JSON-объект (без ```). После этой строки ничего не добавляй."
    )
    return [
        "Ты — эксперт по разбору учебных решений.",
        "Сверстай поле task по тексту условия: title, description, difficulty, tags с весами из текста. "
        "В solutions ровно один элемент: переданный код в solution.code, success по факту.",
        "Заполни analysis.task_compliance: tag_alignment для каждого тега из task.tags; "
        "нужны required_weight, applied, score (1..10), evidence.",
        "Добавь summary, detailed_analysis, strengths, weaknesses, recommendations, correctness, "
        "code_quality_score и при необходимости блок «Временная сложность решения».",
        tail_instr,
        "Структура JSON (ключи):",
        schema,
        "",
        "Условие задачи:",
        task_context.strip(),
        "",
        "Код:",
        f"```python\n{code}\n```",
    ]


def _analyze_prompt_lines_with_task(task: AnalyzeTaskInput, task_context_extra: str | None, code: str) -> list[str]:
    fixed = {"id": task.id, "title": task.title, "description": task.description, "difficulty": task.difficulty}
    task_json = json.dumps(fixed, ensure_ascii=False, indent=2)
    tail_instr = (
        "После произвольного текстового разбора в конце ответа выведи ровно одну финальную строку: префикс "
        + EDU_REPORT_JSON
        + " сразу затем один валидный JSON-объект (без ```). После этой строки ничего не добавляй."
    )
    lines: list[str] = [
        "Ты — эксперт по разбору учебных решений.",
        "Ниже переданы четыре поля задания с платформы. В финальном JSON скопируй их в report.task дословно.",
        'Сгенерируй report.task.tags — массив {"name", "weight"} по смыслу описания.',
        "Сгенерируй solutions и analysis: summary, task_compliance, tag_alignment по именам из task.tags.",
        "Для каждого task.tags[].name заполни required_weight, score (1..10), evidence.",
        "Добавь detailed_analysis, strengths, weaknesses, recommendations, correctness и code_quality_score.",
        tail_instr,
        "Структура JSON:",
        _schema_block(),
        "",
        "Входные поля задания (не меняй в ответе):",
        task_json,
    ]
    if task_context_extra and task_context_extra.strip():
        lines.extend(["", "Дополнительный текст условия (учти при разборе):", task_context_extra.strip()])
    lines.extend(["", "Код:", f"```python\n{code}\n```"])
    return lines


def analyze_code(*, code: str, task: AnalyzeTaskInput | None = None, task_context: str | None = None) -> AnalyzeResult:
    ensure_model_loaded()
    assert runtime.tokenizer is not None and runtime.model is not None
    if task is not None:
        prompt_lines = _analyze_prompt_lines_with_task(task, task_context, code)
    else:
        tc = (task_context or "").strip()
        prompt_lines = _analyze_prompt_lines_legacy(tc, code)
    prompt = "\n".join(prompt_lines)
    device = _infer_device(runtime.model)
    inputs = runtime.tokenizer(prompt, return_tensors="pt").to(device)
    prompt_length = inputs["input_ids"].shape[1]
    with torch.no_grad():
        out = runtime.model.generate(
            **inputs,
            max_new_tokens=runtime.settings.max_new_tokens,
            do_sample=True,
            temperature=0.3,
            top_p=0.9,
            pad_token_id=runtime.tokenizer.pad_token_id,
            eos_token_id=runtime.tokenizer.eos_token_id,
        )
    completion_tokens = out[0][prompt_length:]
    raw_completion = runtime.tokenizer.decode(completion_tokens, skip_special_tokens=True).strip()
    parsed = parse_model_completion(raw_completion)
    if task is not None and parsed.report_json is not None:
        _inject_client_task(parsed.report_json, task)
    return AnalyzeResult(
        analysis=parsed.analysis,
        tag_scores=parsed.tag_scores,
        report_json=parsed.report_json,
        raw_completion=raw_completion,
    )
