import base64

import pytest
import responses

import db
from models import Holding
from services import simplefin

CLAIM = "https://bridge.example/simplefin/claim/TOK"
ACCESS = "https://user:pw@bridge.example/simplefin"


@pytest.fixture(autouse=True)
def _bridge_host(monkeypatch):
    monkeypatch.setenv("SIMPLEFIN_HOSTS", "bridge.example")


TOKEN = base64.b64encode(CLAIM.encode()).decode()
PAYLOAD = {
    "errors": [],
    "accounts": [
        {"id": "ACT-111111", "name": "Checking", "org": {"name": "Test Bank"}, "currency": "USD", "balance": "1200.50"},
        {"id": "ACT-222222", "name": "Card", "org": {"name": "Test Bank"}, "currency": "USD", "balance": "-300.00"},
        {"id": "ACT-333333", "name": "Euro", "org": {"name": "Test Bank"}, "currency": "EUR", "balance": "10"},
    ],
}


@responses.activate
def test_connect_sync_and_status(client):
    responses.post(CLAIM, body=ACCESS)
    responses.get("https://bridge.example/simplefin/accounts", json=PAYLOAD)
    assert client.get("/api/simplefin").get_json()["connected"] is False
    assert client.post("/api/simplefin/connect", json={"setup_token": TOKEN}).status_code == 201
    r = client.post("/api/simplefin/sync")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["row_errors"]) == 2 and body["money_check"] == 1200.5
    with client.application.app_context():
        h = db.session().query(Holding).all()
        assert [(x.symbol, x.market_value) for x in h] == [("SF-111111", 1200.5)]
    # credentials were sent as basic auth, not in the stored status
    assert responses.calls[-1].request.headers["Authorization"].startswith("Basic ")
    assert client.get("/api/simplefin").get_json()["last_status"].startswith("ok")
    assert client.delete("/api/simplefin").status_code == 204
    assert client.get("/api/simplefin").get_json()["connected"] is False


@responses.activate
def test_access_url_stored_encrypted(client):
    responses.post(CLAIM, body=ACCESS)
    client.post("/api/simplefin/connect", json={"setup_token": TOKEN})
    with client.application.app_context():
        from models import SimpleFinConfig

        raw = db.session().query(SimpleFinConfig).one().access_url_encrypted
        assert "pw" not in raw and raw


@responses.activate
def test_claim_failure_and_bad_token(client):
    responses.post(CLAIM, status=403)
    assert client.post("/api/simplefin/connect", json={"setup_token": TOKEN}).status_code == 422
    assert client.post("/api/simplefin/connect", json={"setup_token": "!!notb64"}).status_code == 422
    assert client.post("/api/simplefin/connect", json={}).status_code == 400
    assert client.post("/api/simplefin/sync").status_code == 422


@responses.activate
def test_refused_access_message(client):
    responses.post(CLAIM, body=ACCESS)
    responses.get("https://bridge.example/simplefin/accounts", status=403)
    client.post("/api/simplefin/connect", json={"setup_token": TOKEN})
    r = client.post("/api/simplefin/sync")
    assert r.status_code == 422 and "reconnect" in r.get_json()["error"]


def test_parse_unreadable_balance():
    res = simplefin.to_parse_result({"accounts": [{"id": "A1", "name": "x", "balance": "n/a"}]})
    assert not res.rows and res.row_errors


def test_scheduler_noop_when_disconnected(app):
    from services import scheduler

    scheduler.simplefin_sync(app)
    assert scheduler.RUNS["simplefin_sync"]["status"] == "ok"
    pytest.importorskip("responses")


@pytest.mark.parametrize(
    "host",
    [
        "http://bridge.example/c",
        "https://localhost/c",
        "https://127.0.0.1/c",
        "https://10.0.0.5/c",
        "https://intranet/c",
        "https://nas.local/c",
        "https://evil.example/c",
        "https://bridge.example:8443/c",
        "https://u:p@bridge.example/c",
    ],
)
def test_claim_rejects_internal_hosts(host):
    with pytest.raises(ValueError):
        simplefin._check_public_https(host)
