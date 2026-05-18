from __future__ import annotations
import argparse
import csv
import io
import json
import sys
from typing import Any, Iterable
_TAG_KEYS = frozenset({'tag', 'name', 'topic', 'skill', 'label', 'id', 'key', 'тег', 'навык', 'категория'})
_SCORE_KEYS = frozenset({'score', 'grade', 'value', 'points', 'mark', 'weight', 'rating', 'балл', 'оценка', 'рейтинг'})
_TAG_MAP_PARENT_KEYS = frozenset({'per_tag', 'scores_by_tag', 'tag_scores', 'by_tag', 'rubric', 'evaluations', 'оценки_по_тегам', 'теги'})

def _as_float(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        x = x.strip().replace(',', '.')
        try:
            return float(x)
        except ValueError:
            return None
    return None

def _iter_tag_score_objects(o: Any, out: list[tuple[str, float]]) -> None:
    if isinstance(o, dict):
        for parent in _TAG_MAP_PARENT_KEYS:
            if parent in o and isinstance(o[parent], dict):
                for k, v in o[parent].items():
                    if isinstance(k, str):
                        num = _as_float(v)
                        if num is not None:
                            out.append((k.strip(), num))
        str_keys = [k for k in o.keys() if isinstance(k, str)]
        if str_keys and all((_as_float(o[k]) is not None for k in str_keys)):
            if not any((k in _TAG_KEYS for k in o)) and (not any((k in _SCORE_KEYS for k in o))):
                for k in str_keys:
                    v = o[k]
                    num = _as_float(v)
                    if num is not None and k not in _SCORE_KEYS:
                        out.append((k.strip(), num))
        tag_val: str | None = None
        for tk in _TAG_KEYS:
            if tk in o and isinstance(o[tk], str) and o[tk].strip():
                tag_val = o[tk].strip()
                break
        score_val: float | None = None
        for sk in _SCORE_KEYS:
            if sk in o:
                score_val = _as_float(o[sk])
                if score_val is not None:
                    break
        if tag_val is not None and score_val is not None:
            out.append((tag_val, score_val))
        for v in o.values():
            _iter_tag_score_objects(v, out)
    elif isinstance(o, list):
        for item in o:
            _iter_tag_score_objects(item, out)

def extract_tag_scores(data: Any) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    _iter_tag_score_objects(data, out)
    seen: dict[str, float] = {}
    for tag, score in out:
        seen[tag] = score
    return [(t, seen[t]) for t in seen]

def _load_json(path: str) -> Any:
    if path == '-':
        raw = sys.stdin.read()
    else:
        with open(path, encoding='utf-8-sig') as f:
            raw = f.read()
    return json.loads(raw)

def _print_table(pairs: list[tuple[str, float]]) -> None:
    w = max(len('тег'), max((len(t) for t, _ in pairs), default=0))
    print(f"{'тег':<{w}}  оценка")
    print('-' * (w + 10))
    for tag, score in sorted(pairs, key=lambda x: x[0].lower()):
        print(f'{tag:<{w}}  {score}')

def _print_csv(pairs: list[tuple[str, float]], stream: io.TextIOBase) -> None:
    w = csv.writer(stream)
    w.writerow(['tag', 'score'])
    for tag, score in sorted(pairs, key=lambda x: x[0].lower()):
        w.writerow([tag, score])

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('json_file', help='Путь к JSON или - для stdin')
    ap.add_argument('--format', choices=('table', 'json', 'csv'), default='table', help='Формат вывода (по умолчанию table)')
    args = ap.parse_args()
    try:
        data = _load_json(args.json_file)
    except OSError as e:
        print(f'Ошибка чтения: {e}', file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f'Невалидный JSON: {e}', file=sys.stderr)
        return 1
    pairs = extract_tag_scores(data)
    if not pairs:
        print('Не найдено пар (тег, оценка). Проверьте структуру JSON.', file=sys.stderr)
        return 2
    if args.format == 'table':
        _print_table(pairs)
    elif args.format == 'json':
        print(json.dumps({'tags': [{'tag': t, 'score': s} for t, s in sorted(pairs)]}, ensure_ascii=False, indent=2))
    else:
        _print_csv(pairs, sys.stdout)
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
