import pytest

from services import crypto


def test_health_is_public(authed_app):
    assert authed_app.test_client().get("/api/health").get_json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "s3cret-but-no-bearer-prefix-x"}, {"Authorization": "Bearer "}])
def test_api_rejects_missing_or_bad_token(authed_app, headers):
    r = authed_app.test_client().get("/api/profile", headers=headers)
    assert r.status_code == 401 and r.get_json() == {"error": "unauthorized"}


def test_api_accepts_valid_token(authed_app):
    r = authed_app.test_client().get("/api/profile", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_options_preflight_not_blocked(authed_app):
    assert authed_app.test_client().options("/api/profile").status_code != 401


def test_empty_token_disables_auth(client):
    assert client.get("/api/profile").status_code == 200


def test_unknown_route_is_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and "error" in r.get_json()


def test_validation_errors_are_400_json(client):
    r = client.put("/api/settings/llm", json={"provider": 123, "fast_model": ["x"]})
    assert r.status_code == 400 and r.get_json()["error"] == "validation"


def test_crypto_roundtrip(app):
    with app.app_context():
        tok = crypto.encrypt("sk-secret")
        assert tok != "sk-secret" and "sk-secret" not in tok
        assert crypto.decrypt(tok) == "sk-secret"
        assert crypto.encrypt("") == "" and crypto.decrypt("") == ""


def test_crypto_wrong_secret_or_garbage_decrypts_to_empty(app):
    with app.app_context():
        tok = crypto.encrypt("sk-secret")
        assert crypto.decrypt("not-a-token") == ""
        app.config["APP_SECRET"] = "a-different-secret"
        assert crypto.decrypt(tok) == ""
