from types import SimpleNamespace

import pytest

from services import spending as S
from services import spending_goals as G
from tests.test_household import _flows

AGES = {"SELF": 45.0, "SPOUSE": 43.0}


def _goal(**kw):
    d = dict(
        id=1,
        name="Travel",
        annual_amount=12_000.0,
        start_basis="YEARS_AFTER_RETIREMENT",
        start_value=0.0,
        end_basis="YEARS_AFTER_RETIREMENT",
        end_value=15.0,
        owner="SELF",
        real_inflation=0.0,
        smile_applies=False,
        enabled=True,
    )
    d.update(kw)
    return SimpleNamespace(**d)


def test_years_after_retirement_window():
    g = _goal()  # retire in 10 years, 15-year window -> years 10..24
    assert G.goal_amount(g, 9, AGES, 10) == 0
    assert G.goal_amount(g, 10, AGES, 10) == 12_000
    assert G.goal_amount(g, 24, AGES, 10) == 12_000
    assert G.goal_amount(g, 25, AGES, 10) == 0


def test_age_window_follows_owner():
    g = _goal(start_basis="AGE", start_value=60, end_basis="AGE", end_value=70, owner="SPOUSE")  # spouse is 43 -> years 17..26
    assert G.goal_amount(g, 16, AGES, 10) == 0
    assert G.goal_amount(g, 17, AGES, 10) == 12_000
    assert G.goal_amount(g, 27, AGES, 10) == 0


def test_open_ended_disabled_and_inflation():
    assert G.goal_amount(_goal(end_value=None), 49, AGES, 10) == 12_000
    assert G.goal_amount(_goal(enabled=False), 12, AGES, 10) == 0
    assert G.goal_amount(_goal(real_inflation=0.02), 12, AGES, 10) == pytest.approx(12_000 * 1.02**12)


def test_smile_scales_only_when_applied():
    m = S.load({"smile": True})  # slow-go from 75 at 0.92
    y = 31  # age 76
    assert G.goal_amount(_goal(end_value=None, smile_applies=True), y, AGES, 10, m) == pytest.approx(12_000 * 0.92)
    assert G.goal_amount(_goal(end_value=None), y, AGES, 10, m) == 12_000


def test_no_goals_leaves_flows_identical_and_goals_add_spend():
    base = _flows()
    assert (_flows(spending_goals=[]).extra_spend == base.extra_spend).all()
    with_goal = _flows(spending_goals=[_goal()])
    y = with_goal.retire_y
    # health cost can move too (extra withdrawals raise MAGI and so change the ACA credit), so compare the non-health part
    nonhealth = lambda f: f.extra_spend - f.breakdown["health"]
    assert nonhealth(with_goal)[y] - nonhealth(base)[y] == pytest.approx(12_000)
    assert with_goal.breakdown["spending_goals"][y] == 12_000
    assert with_goal.extra_spend[y - 1] == base.extra_spend[y - 1]


def test_summarize_totals():
    out = G.summarize([_goal(), _goal(id=2, name="Off", enabled=False)], AGES, 10, 50)
    assert out["lifetime_real"] == 15 * 12_000
    assert out["goals"][0]["first_age"] == 55.0 and out["goals"][1]["lifetime_real"] == 0


def test_routes_crud_validation_and_impact(client):
    r = client.post("/api/spending-goals", json={"name": "Travel", "annual_amount": 15000, "end_value": 15})
    assert r.status_code == 201
    gid = r.get_json()["id"]
    assert client.post("/api/spending-goals", json={"name": "x", "annual_amount": -1}).status_code == 422
    assert client.post("/api/spending-goals", json={"name": "x", "annual_amount": 1, "start_value": 5, "end_value": 3}).status_code == 422
    assert client.put(f"/api/spending-goals/{gid}", json={"name": "Travel", "annual_amount": 20000, "end_value": 10}).get_json()["annual_amount"] == 20000
    listed = client.get("/api/spending-goals").get_json()
    assert len(listed["goals"]) == 1 and listed["costs"][0]["lifetime_real"] > 0
    assert "travel" in client.get("/api/spending-goals/presets").get_json()["presets"]
    imp = client.get("/api/spending-goals/impact?n_sims=300").get_json()
    assert imp["has_goals"] and imp["success_rate_with"] <= imp["success_rate_without"]
    assert client.delete(f"/api/spending-goals/{gid}").status_code == 204
    assert client.delete(f"/api/spending-goals/{gid}").status_code == 404
