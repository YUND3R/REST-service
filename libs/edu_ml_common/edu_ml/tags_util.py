from __future__ import annotations

def normalize_three_tags(tags: list[str]) -> tuple[str, str, str]:
    cleaned = [t.strip() for t in tags if t and isinstance(t, str) and t.strip()]
    if not cleaned:
        raise ValueError('Нужен хотя бы один непустой тег')
    cleaned = cleaned[:3]
    while len(cleaned) < 3:
        cleaned.append(cleaned[-1])
    return (cleaned[0], cleaned[1], cleaned[2])
