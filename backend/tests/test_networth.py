from datetime import UTC, datetime

import pytest

import db
from models import Holding, NetWorthSnapshot
from services import ingestion, networth


def test_project_balance_hand_computed():
    # 12 months at 12%/yr = 1%/month: 1000*1.01^12 + 100*(1.01^12-1)/0.01
    f = 1.01**12
    assert networth.project_balance(1000, 12, 0.12, 100) == pytest.approx(1000 * f + 100 * (f - 1) / 0.01)
    assert networth.project_balance(1000, 3, 0.0, 100) == 1300
    assert networth.project_balance(1000, 0, 0.1, 100) == 1000


def _row(day, total):
    return {"taken_at": f"{day}T12:00:00", "total": total}


def test_milestones_reached_next_and_fi():
    series = [_row("2026-01-05", 40_000), _row("2026-02-05", 110_000), _row("2026-03-05", 95_000)]
    m = networth.milestones(series, fi_number=300_000)
    levels = {r["level"]: r["reached_on"] for r in m["reached"]}
    assert levels[100_000] == "2026-02-05" and levels[25_000] == "2026-01-05" and 250_000 not in levels
    assert m["next"] == {"level": 250_000, "remaining": 140_000, "is_fi": False}
    fi = networth.milestones([_row("2026-01-05", 310_000)], fi_number=300_000)
    assert any(r["is_fi"] and r["level"] == 300_000 for r in fi["reached"])


def test_monthly_drift_vs_projection():
    series = [_row("2026-01-31", 10_000), _row("2026-02-10", 10_000), _row("2026-02-28", 11_500), _row("2026-03-31", 12_000)]
    d = networth.monthly_drift(series, 0.0, 1000)
    assert [r["month"] for r in d] == ["2026-01", "2026-02", "2026-03"]
    assert d[0]["planned"] == 10_000 and d[0]["drift"] == 0
    assert d[1]["actual"] == 11_500 and d[1]["planned"] == 11_000 and d[1]["drift"] == 500
    assert d[2]["planned"] == 12_000 and d[2]["drift"] == 0
    assert networth.monthly_drift([], 0.05, 100) == []


def test_snapshot_is_idempotent_per_day_and_has_breakdown(client):
    a = client.post("/api/accounts", json={"name": "Brokerage", "tax_bucket": "TAXABLE_BROKERAGE"}).get_json()
    client.post("/api/liabilities", json={"name": "Car", "kind": "AUTO", "balance": 5000})
    with client.application.app_context():
        s = db.session()
        s.add(Holding(account_id=a["id"], symbol="VTI", shares=1, market_value=20_000, asset_class="US_EQUITY"))
        s.commit()
        day = datetime(2026, 5, 4, 15, tzinfo=UTC)
        ingestion.snapshot_net_worth(s, day)
        s.commit()
        s.query(Holding).one().market_value = 25_000
        ingestion.snapshot_net_worth(s, day.replace(hour=20))
        s.commit()
        rows = [r for r in s.query(NetWorthSnapshot).all() if r.taken_at.date().isoformat() == "2026-05-04"]
        assert len(rows) == 1
        assert rows[0].total == 20_000 and rows[0].breakdown["assets"]["TAXABLE_BROKERAGE"] == 25_000
        assert rows[0].breakdown["liabilities"] == {"AUTO": 5000}


def test_summary_endpoint(client):
    client.put("/api/profile", json={"monthly_contribution": 500, "monthly_expenses_retirement": 4000})
    r = client.get("/api/networth/summary").get_json()
    assert r["series"] == [] and r["drift"] == [] and r["milestones"]["next"]["level"] == 10_000
    assert client.get("/api/networth/history").get_json() == []
