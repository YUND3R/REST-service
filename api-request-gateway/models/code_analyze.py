from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_lock = Lock()
_runtime: CodeAnalyzeRuntime | None = None


@dataclass
class CodeAnalyzeRuntime:
    model_id: str
    tokenizer: Any
    model: Any
    device: str


def _extract_json_block(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("Model output did not contain JSON object")
    return json.loads(m.group(0))


def score_to_difficulty(score: int) -> str:
    if score <= 4:
        return "hard"
    if score <= 7:
        return "medium"
    return "easy"


class CodeAnalyzeModel:
    def __init__(self) -> None:
        self._rt: CodeAnalyzeRuntime | None = None

    def ensure_loaded(self) -> CodeAnalyzeRuntime:
        global _runtime
        with _lock:
            if _runtime is not None:
                self._rt = _runtime
                return _runtime
            model_id = os.environ.get("CODE_ANALYZE_MODEL_ID", "Vilyam888/Code_analyze.1.0")
            load_in_4bit = os.environ.get("LOAD_IN_4BIT", "true").lower() in ("1", "true", "yes")
            logger.info("Loading Code Analyze model: %s", model_id)
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

            tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            quant = None
            if load_in_4bit and torch.cuda.is_available():
                quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
            device_map = "auto" if torch.cuda.is_available() else None
            kwargs: dict[str, Any] = {
                "trust_remote_code": True,
            }
            if quant is not None:
                kwargs["quantization_config"] = quant
                kwargs["device_map"] = device_map or "auto"
            elif torch.cuda.is_available():
                kwargs["device_map"] = "auto"
            mdl = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
            if not torch.cuda.is_available():
                mdl = mdl.to("cpu")
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            _runtime = CodeAnalyzeRuntime(model_id=model_id, tokenizer=tok, model=mdl, device=dev)
            self._rt = _runtime
            logger.info("Code Analyze model loaded on %s", dev)
            return _runtime

    def build_prompt(self, task_description: str, code: str) -> str:
        rt = self.ensure_loaded()
        system = (
            "You are an expert programming tutor. Analyze student code and output a single JSON object "
            "with keys: score (1-10 int), weak_spots (array of objects with optional line,issue,hint), "
            "tags (string array of topics), recommendations (string array). No markdown fences, JSON only."
        )
        user = f"Task:\n{task_description}\n\nStudent code:\n{code}\n"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if hasattr(rt.tokenizer, "apply_chat_template"):
            return str(
                rt.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            )
        return f"{system}\n\n{user}"

    def infer_sync(self, task_description: str, code: str) -> dict[str, Any]:
        import torch

        rt = self.ensure_loaded()
        prompt = self.build_prompt(task_description, code)
        inputs = rt.tokenizer(prompt, return_tensors="pt")
        if torch.cuda.is_available():
            inputs = {k: v.to(rt.model.device) for k, v in inputs.items()}
        else:
            inputs = {k: v.to("cpu") for k, v in inputs.items()}
        max_new = int(os.environ.get("MAX_NEW_TOKENS", "1024"))
        with torch.inference_mode():
            out = rt.model.generate(**inputs, max_new_tokens=max_new, do_sample=False)
        gen = out[0][inputs["input_ids"].shape[-1] :]
        text = rt.tokenizer.decode(gen, skip_special_tokens=True)
        parsed = _extract_json_block(text)
        sc = int(parsed.get("score", 5))
        sc = max(1, min(10, sc))
        return {
            "score": sc,
            "weak_spots": parsed.get("weak_spots") or [],
            "tags": list(parsed.get("tags") or []),
            "recommendations": list(parsed.get("recommendations") or []),
        }
