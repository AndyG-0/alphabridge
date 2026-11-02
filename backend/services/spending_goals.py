"""Recurring retirement spending goals (travel, hobbies, family, home) added on top of the base budget.

Pure functions over goal-like objects. Amounts are today's dollars; the planner applies general inflation on top.
Preset amounts in data/spending_goal_presets.json are illustrative and flagged unverified there.
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from services import spending as spending_svc

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "spending_goal_presets.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA_FILE.read_text())


def presets() -> dict:
    d = _data()
    return {"presets": d["presets"], "verified": d["verified"], "notes": d["notes"], "source_url": d["source_url"]}


def _age_at(owner: str, ages: dict[str, float]) -> float:
    return ages.get(owner, ages["SELF"]) if owner != "JOINT" else ages["SELF"]


def _bound(basis: str, value: float, owner_age_now: float, retire_years: float) -> float:
    """Years from now at which a start/end bound falls."""
    return (value - owner_age_now) if basis == "AGE" else retire_years + value


def in_window(goal, y: int, ages_now: dict[str, float], retire_years: float) -> bool:
    """True when simulation year `y` (0 = this year) lies in [start, end)."""
    age_now = _age_at(goal.owner, ages_now)
    start = _bound(goal.start_basis, goal.start_value, age_now, retire_years)
    if y < start - 1e-9:
        return False
    if goal.end_value is None:
        return True
    return y < _bound(goal.end_basis, goal.end_value, age_now, retire_years) - 1e-9


def goal_amount(goal, y: int, ages_now: dict[str, float], retire_years: float, smodel=None) -> float:
    """Today's-dollar cost of one goal in simulation year `y`; zero when disabled or outside its window."""
    if not goal.enabled or goal.annual_amount <= 0 or not in_window(goal, y, ages_now, retire_years):
        return 0.0
    amt = goal.annual_amount * (1 + goal.real_inflation) ** y
    if goal.smile_applies and smodel is not None:
        amt *= spending_svc.phase_multiplier(smodel, ages_now["SELF"] + y)
    return amt


def yearly_extra(goals, ages_now: dict[str, float], retire_years: float, years: int, smodel=None) -> np.ndarray:
    out = np.zeros(years)
    for g in goals:
        for y in range(years):
            out[y] += goal_amount(g, y, ages_now, retire_years, smodel)
    return out


def summarize(goals, ages_now: dict[str, float], retire_years: float, years: int, smodel=None, inflation: float = 0.025) -> dict:
    """Per-goal lifetime cost (today's dollars and nominal) plus by-year rows for a chart."""
    per = []
    rows: list[dict] = [{"year_index": y, "age": round(ages_now["SELF"] + y, 1), "total": 0.0, "goals": {}} for y in range(years)]
    for g in goals:
        series = [goal_amount(g, y, ages_now, retire_years, smodel) for y in range(years)]
        for y, v in enumerate(series):
            if v:
                rows[y]["goals"][g.id] = v
                rows[y]["total"] += v
        active = [y for y, v in enumerate(series) if v]
        per.append(
            {
                "id": g.id,
                "name": g.name,
                "enabled": g.enabled,
                "lifetime_real": sum(series),
                "lifetime_nominal": sum(v * (1 + inflation) ** y for y, v in enumerate(series)),
                "first_age": round(ages_now["SELF"] + active[0], 1) if active else None,
                "last_age": round(ages_now["SELF"] + active[-1], 1) if active else None,
            }
        )
    return {
        "goals": per,
        "lifetime_real": sum(p["lifetime_real"] for p in per),
        "lifetime_nominal": sum(p["lifetime_nominal"] for p in per),
        "rows": [r for r in rows if r["total"]],
    }
