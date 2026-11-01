from datetime import date, datetime, timedelta

import pytest

import db
from models import Account, ActionItem, Holding, IngestionLog, UserProfile
from routes._helpers import get_profile
from services import actions

TODAY = date(2026, 10, 31)


def _profile(**kw):
    p = UserProfile(**{"annual_income": 100_000, "monthly_contribution": 100, "employer_match_rate": 0.5, "employer_match_cap_pct": 0.06, **kw})
    return p


def test_match_capture_flags_shortfall():
    (it,) = actions.match_capture_items(_profile(), TODAY)
    assert it["key"] == "match:2026" and it["dollars"] > 0
    assert it["priority"] >= 80


def test_match_capture_silent_when_captured_or_unset():
    assert actions.match_capture_items(_profile(monthly_contribution=500), TODAY) == []
    assert actions.match_capture_items(_profile(employer_match_rate=0), TODAY) == []


def test_rebalance_item_only_when_breached():
    row = {"breach": True, "asset_class": "US_EQUITY", "current": 0.8, "target": 0.6}
    rb = {"drift": {"breached": True, "total_drift": 0.2, "rows": [row]}, "trades": [{"dollars": -5000}], "est_tax": 10}
    (it,) = actions.rebalance_items(rb, TODAY)
    assert it["key"] == "rebalance:2026-10" and it["where"] == "/portfolio"
    assert actions.rebalance_items({"drift": {"breached": False}}, TODAY) == []
    assert actions.rebalance_items({"drift": None}, TODAY) == []


def test_harvest_respects_minimum():
    h = {"total_loss": 5000, "total_est_savings": 1200, "candidates": [{}]}
    assert len(actions.harvest_items({"harvest": h}, TODAY)) == 1
    assert actions.harvest_items({"harvest": {**h, "total_est_savings": 10}}, TODAY) == []
    assert actions.harvest_items({"harvest": None}, TODAY) == []


def test_roth_item_needs_near_term_conversion():
    year = {"year": 2027, "age": 50, "conversion": 40_000, "conversion_tax": 4000}
    best = {"strategy": "fill", "label": "Fill 22%", "total_converted": 90_000, "lifetime_cost": 400, "vs_none": {"lifetime_cost": 5400}, "years": [year]}
    plan = {"best": "fill", "plans": [best]}
    (it,) = actions.roth_items(plan, TODAY)
    assert it["key"] == "roth:2027"
    plan["plans"][0]["years"][0]["year"] = 2035
    assert actions.roth_items(plan, TODAY) == []
    assert actions.roth_items({"best": None, "plans": []}, TODAY) == []


def test_stale_statement(app):
    s = db.session()
    a = Account(name="Brokerage", institution="Fidelity", tax_bucket="TAXABLE_BROKERAGE")
    s.add(a)
    s.flush()
    s.add(Holding(account_id=a.id, symbol="VTI", shares=10, current_price=100, market_value=1000))
    s.add(IngestionLog(filename="s.csv", account_id=a.id, status="OK", created_at=datetime(2026, 8, 1)))
    s.commit()
    (it,) = actions.stale_statement_items(s, TODAY)
    assert it["title"] == "Refresh Brokerage"
    assert actions.stale_statement_items(s, date(2026, 8, 10)) == []


def test_year_end_window_and_applicability(app):
    s = db.session()
    p = get_profile()
    assert actions.year_end_items(s, p, date(2026, 6, 1)) == []
    keys = {i["key"] for i in actions.year_end_items(s, p, TODAY)}
    assert "year_end:2026:max_401k" in keys and not any("harvest" in k for k in keys)  # no taxable account yet


def test_snooze_done_and_reopen(app):
    s = db.session()
    p = get_profile()
    items = [{"key": "k:1", "kind": "k", "title": "t", "detail": "d", "priority": 90.0, "where": "/", "dollars": None}]
    assert len(actions.feed(s, p, TODAY, items=items)["items"]) == 1
    actions.mark(s, p, "k:1", "snoozed", 3, TODAY)
    assert actions.feed(s, p, TODAY, items=items)["items"] == []
    assert actions.feed(s, p, TODAY, items=items)["hidden"] == 1
    assert actions.feed(s, p, TODAY, include_hidden=True, items=items)["items"][0]["status"] == "snoozed"
    assert len(actions.feed(s, p, TODAY + timedelta(days=4), items=items)["items"]) == 1  # snooze expired
    actions.mark(s, p, "k:1", "done", today=TODAY)
    assert actions.feed(s, p, TODAY + timedelta(days=40), items=items)["items"] == []
    actions.mark(s, p, "k:1", "open", today=TODAY)
    assert len(actions.feed(s, p, TODAY, items=items)["items"]) == 1
    with pytest.raises(ValueError):
        actions.mark(s, p, "k:1", "bogus")


def test_notify_dedupes_and_retries(app, monkeypatch):
    from services import notifier

    s = db.session()
    p = get_profile()
    items = [
        {"key": "a:1", "kind": "a", "title": "hi", "detail": "d", "priority": 90.0, "where": "/", "dollars": None},
        {"key": "b:1", "kind": "b", "title": "lo", "detail": "d", "priority": 10.0, "where": "/", "dollars": None},
    ]
    calls = []
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: calls.append(a[0]) or "discord")
    assert actions.notify_new(s, p, TODAY, items=items) == ["a:1"]
    assert actions.notify_new(s, p, TODAY, items=items) == []
    assert calls == ["hi"]

    def boom(*a, **k):
        raise RuntimeError("no channel")

    s.query(ActionItem).delete()
    s.commit()
    monkeypatch.setattr(notifier, "notify", boom)
    assert actions.notify_new(s, p, TODAY, items=items) == []
    assert s.query(ActionItem).count() == 0  # nothing marked notified, so it retries tomorrow


def test_routes(client):
    client.put("/api/profile", json={"annual_income": 100000, "monthly_contribution": 100, "employer_match_rate": 0.5, "employer_match_cap_pct": 0.06})
    r = client.get("/api/actions").get_json()
    keys = [i["key"] for i in r["items"]]
    assert any(k.startswith("match:") for k in keys)
    assert r["items"] == sorted(r["items"], key=lambda i: -i["priority"])
    k = next(k for k in keys if k.startswith("match:"))
    assert client.post(f"/api/actions/{k}/snooze", json={"days": 0}).status_code == 400
    assert client.post(f"/api/actions/{k}/snooze", json={"days": 5}).status_code == 200
    assert k not in [i["key"] for i in client.get("/api/actions").get_json()["items"]]
    assert client.get("/api/actions?all=1").get_json()["items"]
    assert client.post(f"/api/actions/{k}/reopen").status_code == 200
    assert k in [i["key"] for i in client.get("/api/actions").get_json()["items"]]
    assert client.post(f"/api/actions/{k}/done").status_code == 200
    assert k not in [i["key"] for i in client.get("/api/actions").get_json()["items"]]
