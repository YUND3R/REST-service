from __future__ import annotations
import re
_MAX_LEN = 128
_PATTERN = re.compile('^[\\w.-]+$')

def normalize_user_id(user_id: str) -> str:
    if len(user_id) > _MAX_LEN:
        raise ValueError('X-User-Id слишком длинный')
    if not _PATTERN.match(user_id):
        raise ValueError('X-User-Id: допустимы только буквы, цифры, _, -, .')
    return user_id
