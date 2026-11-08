from fastapi.testclient import TestClient

from caliburn.app import app

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-service-token-secret"}


def test_health_without_credentials():
    assert client.get("/healthz").json() == {"status": "alive"}


def test_auth_fails_closed():
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_models():
    response = client.get("/v1/models", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "caliburn-agent"


def test_chat_fixture_completion():
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "caliburn-agent", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["role"] == "assistant"


def test_chat_fixture_uses_tool_then_observes_result():
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "caliburn-agent", "messages": [{"role": "user", "content": "계산 2 3"}]},
    )
    assert response.status_code == 200
    assert response.json()["caliburn"]["model_steps"] == 2
    assert '"sum": 5.0' in response.json()["choices"][0]["message"]["content"]


def test_streaming_is_explicitly_not_implemented():
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "model": "caliburn-agent",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert response.status_code == 501


def test_task_persists_and_can_be_read():
    created = client.post("/api/v1/tasks", headers=AUTH, json={"prompt": "Fix the tests"})
    assert created.status_code == 202
    data = created.json()
    assert data["state"] == "QUEUED"
    loaded = client.get(f"/api/v1/tasks/{data['id']}", headers=AUTH)
    assert loaded.status_code == 200
    assert loaded.json()["prompt"] == "Fix the tests"


def test_missing_task_is_404():
    assert client.get("/api/v1/tasks/nonexistent", headers=AUTH).status_code == 404
