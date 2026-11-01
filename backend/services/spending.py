"""Spending model: category inflation, the retirement 'smile', event templates and real/nominal views.

Pure functions. Defaults (smile off, zero category differentials) reproduce the flat spending the planner used before.
Figures in data/spending_model.json are illustrative and flagged unverified there.
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "spending_model.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA_FILE.read_text())


class Phase(BaseModel):
    from_age: float = Field(ge=0, le=120)
    multiplier: float = Field(ge=0, le=3)
    name: str = ""


class SpendingModel(BaseModel):
    smile: bool = False
    shares: dict[str, float] = Field(default_factory=dict)  # category -> share of base spend (excl. health); empty = data defaults
    real_inflation: dict[str, float] = Field(default_factory=dict)  # category -> inflation above general, per year
    phases: list[Phase] = Field(default_factory=list)  # empty = data defaults

    @field_validator("real_inflation")
    @classmethod
    def _sane(cls, v):
        if any(abs(x) > 0.15 for x in v.values()):
            raise ValueError("real category inflation must be within +/-15% a year")
        return v

    @field_validator("shares")
    @classmethod
    def _shares(cls, v):
        if v and (any(x < 0 for x in v.values()) or abs(sum(v.values()) - 1) > 1e-6):
            raise ValueError("category shares must be non-negative and sum to 1")
        return v


def load(raw: dict | None) -> SpendingModel:
    return SpendingModel.model_validate(raw or {})


def shares(m: SpendingModel) -> dict[str, float]:
    return m.shares or dict(_data()["categories"])


def real_inflation(m: SpendingModel) -> dict[str, float]:
    return {c: m.real_inflation.get(c, _data()["default_real_inflation"].get(c, 0.0)) for c in shares(m)}


def phases(m: SpendingModel) -> list[dict]:
    ph = [p.model_dump() for p in m.phases] or list(_data()["smile_phases"])
    return sorted(ph, key=lambda p: p["from_age"])


def phase_multiplier(m: SpendingModel, age: float) -> float:
    if not m.smile:
        return 1.0
    cur = 1.0
    for p in phases(m):
        if age >= p["from_age"]:
            cur = p["multiplier"]
    return cur


def category_multiplier(m: SpendingModel, years: float) -> float:
    """Weighted growth of the spending basket above general inflation after `years`."""
    ri = real_inflation(m)
    return sum(s * (1 + ri[c]) ** years for c, s in shares(m).items())


def multiplier(m: SpendingModel, age: float, years_from_now: float) -> float:
    return phase_multiplier(m, age) * category_multiplier(m, max(years_from_now, 0.0))


def is_default(m: SpendingModel) -> bool:
    return not m.smile and all(abs(v) < 1e-12 for v in real_inflation(m).values())


def projection(
    m: SpendingModel, base_annual: float, start_age: float, retire_age: float, end_age: float, inflation: float = 0.025, nominal: bool = False
) -> dict:
    """Year-by-year base spending by category from retirement, in today's dollars or nominal."""
    sh, ri = shares(m), real_inflation(m)
    rows = []
    y0 = max(int(retire_age - start_age + 0.999999), 0)
    for y in range(y0, int(end_age - start_age) + 1):
        age = start_age + y
        ph = phase_multiplier(m, age)
        cats = {c: base_annual * s * ph * (1 + ri[c]) ** y for c, s in sh.items()}
        if nominal:
            f = (1 + inflation) ** y
            cats = {c: v * f for c, v in cats.items()}
        rows.append({"age": round(age, 1), "year_index": y, "phase": _phase_name(m, age), "total": sum(cats.values()), "categories": cats})
    return {"nominal": nominal, "inflation": inflation if nominal else None, "rows": rows, "default_model": is_default(m)}


def _phase_name(m: SpendingModel, age: float) -> str:
    name = "flat"
    if m.smile:
        for p in phases(m):
            if age >= p["from_age"]:
                name = p.get("name") or "phase"
    return name


def to_nominal(real_values: list[float], inflation: float) -> list[float]:
    return [v * (1 + inflation) ** i for i, v in enumerate(real_values)]


def to_real(nominal_values: list[float], inflation: float) -> list[float]:
    return [v / (1 + inflation) ** i for i, v in enumerate(nominal_values)]


def template_names() -> list[str]:
    return list(_data()["event_templates"])


def event_from_template(name: str, start_year: int, amount: float | None = None, owner: str = "JOINT") -> list[dict]:
    """PlannedEvent field dicts for a template (college expands to one row repeating for `years` years)."""
    t = dict(_data()["event_templates"][name])
    years = t.pop("years", 0)
    if amount is not None:
        t["amount"] = amount
    t["start_year"] = start_year
    t["owner"] = owner
    if years:
        t["repeat_until_year"] = start_year + years - 1
    return [t]
