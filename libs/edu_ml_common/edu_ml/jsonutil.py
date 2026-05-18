from __future__ import annotations
import json
import re
from typing import Any

def extract_json_object(text: str) -> dict[str, Any]:
    s = text.strip()
    fence = re.search('```(?:json)?\\s*([\\s\\S]*?)\\s*```', s, re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    start = s.find('{')
    end = s.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError('В тексте не найден JSON-объект')
    return json.loads(s[start:end + 1])
