import db
from models import LLMConfig


def test_llm_key_never_returned_and_not_blanked_by_omission(client):
    r = client.put("/api/settings/llm", json={"provider": "anthropic", "api_key": "sk-ant-TOPSECRET"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "TOPSECRET" not in body and r.get_json()["api_key_set"] is True
    # stored encrypted, not plaintext
    with client.application.app_context():
        stored = db.session().get(LLMConfig, 1).api_key_encrypted
        assert stored and "TOPSECRET" not in stored
    client.put("/api/settings/llm", json={"fast_model": "other-model"})
    assert client.get("/api/settings/llm").get_json()["api_key_set"] is True
    assert "TOPSECRET" not in client.get("/api/settings/llm").get_data(as_text=True)


def test_notification_secrets_never_returned(client):
    r = client.put(
        "/api/settings/notifications",
        json={"discord_webhook": "https://discord.com/api/webhooks/1/TOKENXYZ", "smtp_host": "smtp.x.com", "smtp_password": "hunter2", "smtp_to": "a@b.com"},
    )
    text = r.get_data(as_text=True)
    assert "TOKENXYZ" not in text and "hunter2" not in text
    v = r.get_json()
    assert v["discord_configured"] is True and v["smtp_password_set"] is True and v["smtp_host"] == "smtp.x.com"
    assert "TOKENXYZ" not in client.get("/api/settings/notifications").get_data(as_text=True)


def test_llm_test_without_key_is_400(client, monkeypatch):
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    client.put("/api/settings/llm", json={"provider": "anthropic"})
    r = client.post("/api/settings/llm/test")
    assert r.status_code == 400 and r.get_json()["ok"] is False


def test_llm_test_provider_error_is_502(client, monkeypatch):
    from routes import settings_routes

    def boom(*a, **k):
        raise ConnectionError("upstream down")

    monkeypatch.setattr(settings_routes, "complete", boom)
    r = client.post("/api/settings/llm/test")
    assert r.status_code == 502 and "upstream down" in r.get_json()["error"]


def test_llm_test_ok(client, monkeypatch):
    from routes import settings_routes

    monkeypatch.setattr(settings_routes, "complete", lambda *a, **k: " pong \n")
    assert client.post("/api/settings/llm/test").get_json() == {"ok": True, "reply": "pong"}


def test_notification_test_without_channel_is_400(client):
    r = client.post("/api/settings/notifications/test")
    assert r.status_code == 400 and "No notification channel" in r.get_json()["error"]
