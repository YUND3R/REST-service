import json

import pytest

from models.broken_code_gen import _extract_json_block as _extract_broken
from models.code_analyze import _extract_json_block as _extract_analyze


@pytest.mark.parametrize("fn", [_extract_broken, _extract_analyze])
def test_extract_json_plain(fn):
    assert fn('{"x": 1}') == {"x": 1}


@pytest.mark.parametrize("fn", [_extract_broken, _extract_analyze])
def test_extract_json_embedded(fn):
    assert fn('prefix {"a": true} suffix') == {"a": True}


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError):
        _extract_analyze("no braces here")


def test_extract_json_invalid_inner_raises():
    with pytest.raises(json.JSONDecodeError):
        _extract_analyze("{not json}")
