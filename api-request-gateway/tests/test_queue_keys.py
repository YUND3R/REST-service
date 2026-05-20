from gateway.services.queue import result_key, status_key
from gateway.services.webhook import _safe_url_label


def test_status_result_keys():
    assert status_key("abc") == "status:abc"
    assert result_key("xyz") == "result:xyz"


def test_safe_url_label_strips_path_and_query():
    assert _safe_url_label("https://hooks.example.com/callback?token=secret") == "https://hooks.example.com"
    assert _safe_url_label("https://hooks.example.com:8443/a/b?token=secret") == "https://hooks.example.com:8443"
