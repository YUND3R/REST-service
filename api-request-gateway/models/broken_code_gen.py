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
_runtime: BrokenCodeRuntime | None = None


@dataclass
class BrokenCodeRuntime:
    model_id: str
    tokenizer: Any
    model: Any


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


class BrokenCodeGenModel:
    def __init__(self) -> None:
        self._rt: BrokenCodeRuntime | None = None

    def ensure_loaded(self) -> BrokenCodeRuntime:
        global _runtime
        with _lock:
            if _runtime is not None:
                self._rt = _runtime
                return _runtime
            model_id = os.environ.get("BROKEN_CODE_MODEL_ID", "Vilyam888/Broken_Code_Generation.1.0")
            load_in_4bit = os.environ.get("LOAD_IN_4BIT", "true").lower() in ("1", "true", "yes")
            logger.info("Loading Broken Code Generation model: %s", model_id)
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

            tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            quant = None
            if load_in_4bit and torch.cuda.is_available():
                quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
            kwargs: dict[str, Any] = {"trust_remote_code": True}
            if quant is not None:
                kwargs["quantization_config"] = quant
                kwargs["device_map"] = "auto"
            elif torch.cuda.is_available():
                kwargs["device_map"] = "auto"
            mdl = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
            if not torch.cuda.is_available():
                mdl = mdl.to("cpu")
            _runtime = BrokenCodeRuntime(model_id=model_id, tokenizer=tok, model=mdl)
            self._rt = _runtime
            logger.info("Broken Code Generation model loaded")
            return _runtime

    def build_prompt(self, tags: list[str], difficulty: str) -> str:
        rt = self.ensure_loaded()
        system = (
            "You generate broken-code practice tasks. Output a single JSON object with keys: "
            "title (string), difficulty (string), topic_tags (object map tag->importance), "
            "task_context (string), tests (array), broken_code (string). JSON only, no markdown."
        )
        user = f"Tags: {json.dumps(tags, ensure_ascii=False)}\nDifficulty: {difficulty}\n"
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

    def infer_sync(self, tags: list[str], difficulty: str) -> dict[str, Any]:
        import torch

        rt = self.ensure_loaded()
        prompt = self.build_prompt(tags, difficulty)
        inputs = rt.tokenizer(prompt, return_tensors="pt")
        if torch.cuda.is_available():
            inputs = {k: v.to(rt.model.device) for k, v in inputs.items()}
        else:
            inputs = {k: v.to("cpu") for k, v in inputs.items()}
        max_new = int(os.environ.get("MAX_NEW_TOKENS", "1536"))
        with torch.inference_mode():
            out = rt.model.generate(**inputs, max_new_tokens=max_new, do_sample=False)
        gen = out[0][inputs["input_ids"].shape[-1] :]
        text = rt.tokenizer.decode(gen, skip_special_tokens=True)
        parsed = _extract_json_block(text)
        return {
            "title": str(parsed.get("title", "")),
            "difficulty": str(parsed.get("difficulty", difficulty)),
            "topic_tags": parsed.get("topic_tags") or {},
            "task_context": str(parsed.get("task_context", "")),
            "tests": parsed.get("tests") or [],
            "broken_code": str(parsed.get("broken_code", "")),
        }
