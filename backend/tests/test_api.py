import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from main import app, _response_cache


def _mock_response(
    content: str = "Hello!",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.model = "gemini/gemini-2.0-flash"
    return resp


@pytest.fixture(autouse=True)
def _clear_cache():
    _response_cache.clear()
    yield
    _response_cache.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["keys_configured"], int)
    assert data["cache_enabled"] is True


@patch("main.litellm.completion", return_value=_mock_response())
def test_chat_success(mock_comp, client):
    resp = client.post(
        "/chat",
        json={"session_id": "test-1", "message": "Hi"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "test-1"
    assert data["reply"] == "Hello!"
    meta = data["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.0-flash"
    assert isinstance(meta["latency_ms"], int)
    assert isinstance(meta["input_tokens"], int)
    assert isinstance(meta["output_tokens"], int)
    assert meta["key_id"] is not None
    assert meta["fallback_attempts"] == 0


@patch("main.litellm.completion", return_value=_mock_response())
def test_chat_cache_hit(mock_comp, client):
    resp1 = client.post(
        "/chat",
        json={"session_id": "cache-1", "message": "Hello"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

    resp2 = client.post(
        "/chat",
        json={"session_id": "cache-2", "message": "Hello"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert resp2.json()["metadata"]["key_id"] is None
    assert resp2.json()["metadata"]["fallback_attempts"] == 0
    assert resp2.json()["reply"] == "Hello!"


def test_chat_missing_message(client):
    resp = client.post("/chat", json={"session_id": "v-1", "message": ""})
    assert resp.status_code == 422


def test_chat_missing_session_id(client):
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 422


def test_chat_message_too_long(client):
    resp = client.post(
        "/chat",
        json={"session_id": "v-2", "message": "x" * 4001},
    )
    assert resp.status_code == 422


@patch("main.litellm.completion")
def test_chat_all_keys_fail(mock_comp, client):
    mock_comp.side_effect = type(
        "RateLimitError", (Exception,), {"status_code": 429}
    )()
    resp = client.post(
        "/chat",
        json={"session_id": "fail-1", "message": "hi"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "all providers unavailable"


@patch("main.litellm.completion", return_value=_mock_response())
def test_simulate_failure_key1(mock_comp, client):
    resp = client.post(
        "/chat",
        json={"session_id": "sim-1", "message": "hi"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert resp.status_code == 200
    assert resp.json()["metadata"]["key_id"] == "key_2"
    assert resp.json()["metadata"]["fallback_attempts"] == 1


@patch("main.litellm.completion", return_value=_mock_response())
def test_simulate_failure_all(mock_comp, client):
    resp = client.post(
        "/chat",
        json={"session_id": "sim-2", "message": "hi"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert resp.status_code == 503


@patch("main.litellm.completion", return_value=_mock_response())
def test_get_session_messages(mock_comp, client):
    client.post(
        "/chat",
        json={"session_id": "hist-1", "message": "What is 2+2?"},
    )
    resp = client.get("/sessions/hist-1/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "hist-1"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"
    assert "metadata" in data["messages"][1]


def test_get_session_not_found(client):
    resp = client.get("/sessions/nonexistent/messages")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "session not found"


@patch("main.litellm.completion", return_value=_mock_response())
def test_multi_turn(mock_comp, client):
    client.post(
        "/chat",
        json={"session_id": "multi-1", "message": "My name is Alice"},
    )
    client.post(
        "/chat",
        json={"session_id": "multi-1", "message": "What is my name?"},
    )
    resp = client.get("/sessions/multi-1/messages")
    msgs = resp.json()["messages"]
    assert len(msgs) == 4
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "user"
    assert msgs[3]["role"] == "assistant"
