from gateway.main import _parse_cors_origins


def test_cors_wildcard():
    assert _parse_cors_origins("*") == ["*"]
    assert _parse_cors_origins(" * ") == ["*"]


def test_cors_list():
    assert _parse_cors_origins("https://a.com, https://b.com") == [
        "https://a.com",
        "https://b.com",
    ]


def test_cors_empty_parts_skipped():
    assert _parse_cors_origins("https://a.com,, ") == ["https://a.com"]
