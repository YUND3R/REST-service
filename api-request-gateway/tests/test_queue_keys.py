from gateway.services.queue import result_key, status_key


def test_status_result_keys():
    assert status_key("abc") == "status:abc"
    assert result_key("xyz") == "result:xyz"
