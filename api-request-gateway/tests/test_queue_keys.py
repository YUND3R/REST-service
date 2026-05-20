import hmac

from gateway.services.queue import result_key, status_key
from gateway.services.webhook import _safe_url_label, _webhook_signature_body, build_webhook_headers


def test_status_result_keys():
    assert status_key("abc") == "status:abc"
    assert result_key("xyz") == "result:xyz"


def test_safe_url_label_strips_path_and_query():
    assert _safe_url_label("https://hooks.example.com/callback?token=secret") == "https://hooks.example.com"
    assert _safe_url_label("https://hooks.example.com:8443/a/b?token=secret") == "https://hooks.example.com:8443"


def test_webhook_signature_is_stable(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SIGNING_SECRET", "test-secret")
    body_a = {"b": 2, "a": 1}
    body_b = {"a": 1, "b": 2}
    headers_a = build_webhook_headers(body_a, timestamp=123)
    headers_b = build_webhook_headers(body_b, timestamp=123)

    assert headers_a["X-Webhook-Timestamp"] == "123"
    assert hmac.compare_digest(headers_a["X-Webhook-Signature"], headers_b["X-Webhook-Signature"])
    assert _webhook_signature_body(body_a) == _webhook_signature_body(body_b)
