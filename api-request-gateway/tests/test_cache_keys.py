from gateway.services.cache import (
    analyze_cache_key,
    generate_cache_key,
    pipeline_cache_key,
    stable_json,
)


def test_stable_json_sorts_keys():
    a = stable_json({"z": 1, "a": 2})
    b = stable_json({"a": 2, "z": 1})
    assert a == b


def test_analyze_cache_key_deterministic():
    k1 = analyze_cache_key("t", "x = 1")
    k2 = analyze_cache_key("t", "x = 1")
    assert k1 == k2
    assert k1.startswith("cache:analyze:")


def test_analyze_cache_key_differs_on_code():
    assert analyze_cache_key("t", "a") != analyze_cache_key("t", "b")


def test_generate_cache_key_sorts_tags():
    k1 = generate_cache_key(["b", "a"], "medium")
    k2 = generate_cache_key(["a", "b"], "medium")
    assert k1 == k2


def test_pipeline_cache_matches_analyze_payload_hash_pattern():
    k = pipeline_cache_key("task", "code")
    assert k.startswith("cache:pipeline:")
    assert k == analyze_cache_key("task", "code").replace("cache:analyze:", "cache:pipeline:", 1)
