from __future__ import annotations


def parse_cors_origins(raw: str) -> list[str]:
    s = (raw or "").strip()
    if not s or s == "*":
        return ["*"]
    return [p.strip() for p in s.split(",") if p.strip()]
