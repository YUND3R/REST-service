from __future__ import annotations
import json
from typing import Any

def clamp_tag_score(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x < 1.0:
        return 1.0
    if x > 10.0:
        return 10.0
    return x

def merge_tag_sample_blob(prev_raw: str | None, score: float) -> str:
    if prev_raw:
        try:
            o = json.loads(prev_raw)
            sm = float(o.get('sum', 0.0))
            cnt = int(o.get('count', 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            sm, cnt = (0.0, 0)
    else:
        sm, cnt = (0.0, 0)
    sm += score
    cnt += 1
    return json.dumps({'sum': sm, 'count': cnt}, ensure_ascii=False)

def mean_from_blob(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        o = json.loads(raw)
        sm = float(o.get('sum', 0.0))
        cnt = int(o.get('count', 0))
        if cnt <= 0:
            return None
        return sm / cnt
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
