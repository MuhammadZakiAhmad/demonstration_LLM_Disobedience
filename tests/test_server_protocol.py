import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import model_server


@pytest.fixture
def fake_server():
    backend = model_server.FakeBackend()
    server = model_server.create_server(
        backend=backend,
        host="127.0.0.1",
        port=0,
        config_sha256="test-config-hash",
        backend_mode="fake",
        environment=None,
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield server, backend, base_url
    finally:
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get_json(url):
    with urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post_raw(url, data: bytes):
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    return urlopen(request, timeout=5)


def test_health_check_reports_ready_fake_backend(fake_server):
    _server, _backend, base_url = fake_server
    status, payload = _get_json(f"{base_url}/health")
    assert status == 200
    assert payload["status"] == "ready"
    assert payload["fake_backend"] is True
    assert payload["backend_mode"] == "fake"
    assert payload["model"]["eos_token_ids"] == [151643, 151645]
    assert payload["config_sha256"] == "test-config-hash"


def test_generate_protocol(fake_server):
    _server, backend, base_url = fake_server
    status, payload = _post_json(
        f"{base_url}/generate",
        {
            "messages": [
                {"role": "system", "content": "Never use a hyphen."},
                {"role": "user", "content": "Write an email."},
            ],
            "generation_config": {
                "max_new_tokens": 32,
                "do_sample": False,
                "repetition_penalty": 1.0,
            },
            "seed": 42,
        },
    )
    assert status == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert "Protocol test" in result["generated_text"]
    assert "[fake call 1, seed 42]" in result["generated_text"]
    assert result["finish_reason"] == "eos"
    assert result["metadata"]["seed"] == 42
    assert "server_request_duration_seconds" in result["request_metadata"]
    assert backend.calls == 1


def test_malformed_json_returns_400_and_does_not_crash_server(fake_server):
    _server, _backend, base_url = fake_server
    with pytest.raises(HTTPError) as exc_info:
        _post_raw(f"{base_url}/generate", b"{this is not json")
    assert exc_info.value.code == 400
    body = json.loads(exc_info.value.read().decode("utf-8"))
    assert body["ok"] is False
    assert body["error"]["type"] == "request_validation"

    status, health = _get_json(f"{base_url}/health")
    assert status == 200
    assert health["status"] == "ready"


def test_invalid_payload_returns_400(fake_server):
    _server, _backend, base_url = fake_server
    with pytest.raises(HTTPError) as exc_info:
        _post_json(
            f"{base_url}/generate",
            {
                "messages": [{"role": "assistant", "content": "not allowed"}],
                "generation_config": {"max_new_tokens": 32, "do_sample": False},
                "seed": 42,
            },
        )
    assert exc_info.value.code == 400


def test_unknown_generation_key_returns_400(fake_server):
    _server, _backend, base_url = fake_server
    with pytest.raises(HTTPError) as exc_info:
        _post_json(
            f"{base_url}/generate",
            {
                "messages": [{"role": "user", "content": "Write an email."}],
                "generation_config": {
                    "max_new_tokens": 32,
                    "do_sample": False,
                    "min_p": 0.0,
                },
                "seed": 42,
            },
        )
    assert exc_info.value.code == 400


def test_sequential_requests(fake_server):
    _server, backend, base_url = fake_server
    for seed in (1, 2, 3):
        status, payload = _post_json(
            f"{base_url}/generate",
            {
                "messages": [{"role": "user", "content": "Write an email."}],
                "generation_config": {"max_new_tokens": 8, "do_sample": False},
                "seed": seed,
            },
        )
        assert status == 200
        assert f"seed {seed}" in payload["result"]["generated_text"]
    assert backend.calls == 3


def test_shutdown_endpoint(fake_server):
    server, _backend, base_url = fake_server
    status, payload = _post_json(f"{base_url}/shutdown", {"confirm": "shutdown"})
    assert status == 200
    assert payload["ok"] is True
    assert server.state.shutting_down is True
    shutdown_event = getattr(server, "_BaseServer__is_shut_down")
    assert shutdown_event.wait(timeout=5)


def test_shutdown_requires_confirmation(fake_server):
    _server, _backend, base_url = fake_server
    with pytest.raises(HTTPError) as exc_info:
        _post_json(f"{base_url}/shutdown", {"confirm": "no"})
    assert exc_info.value.code == 400


def test_non_localhost_binding_requires_explicit_flag():
    with pytest.raises(ValueError):
        model_server.create_server(
            backend=model_server.FakeBackend(),
            host="0.0.0.0",
            port=0,
            config_sha256=None,
            backend_mode="fake",
        )
