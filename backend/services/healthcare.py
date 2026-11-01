"""Health-care costs: Medicare Part B/D + IRMAA + Medigap, pre-65 ACA premiums, HSA accumulate/spend, and long-term-care events.

Pure math in today's dollars; callers apply `household.health_adj` for health inflation. Constants live in data/healthcare.json
and data/tax_tables (IRMAA). MAGI uses the current-year estimate; real IRMAA looks back two years (stated in the output)."""

import json
from functools import lru_cache
from pathlib import Path

from services import aca, hsa, tax

DATA = Path(__file__).resolve().parents[1] / "data" / "healthcare.json"
LTC_MODES = ("EXPECTED", "STRESS")


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text())


def retrieved_on() -> str:
    return _data()["retrieved_on"]


def irmaa_surcharge_monthly(magi: float, status: str, year: int) -> float:
    """Part B + Part D IRMAA surcharge per enrollee per month."""
    i = tax.irmaa(magi, status, year)
    return i["part_b_surcharge_monthly"] + i["part_d_surcharge_monthly"]


def medicare_cost(magi: float, status: str, year: int, people: int = 1, medigap: bool = True) -> dict:
    """Annual Medicare cost for `people` enrollees: Part B + Part D (+ Medigap) plus any IRMAA surcharge."""
    d, i = _data(), tax.irmaa(magi, status, year)
    n = max(people, 0)
    b, pd = i["part_b_total_monthly"], d["part_d_base_monthly"]
    mg = d["medigap_monthly_per_person"] if medigap else 0.0
    return {
        "year": year,
        "magi": magi,
        "irmaa_tier": i["tier"],
        "part_b_monthly": b,
        "part_d_monthly": pd + i["part_d_surcharge_monthly"],
        "medigap_monthly": mg,
        "irmaa_monthly": i["part_b_surcharge_monthly"] + i["part_d_surcharge_monthly"],
        "per_person_annual": 12 * (b + pd + i["part_d_surcharge_monthly"] + mg),
        "annual": n * 12 * (b + pd + i["part_d_surcharge_monthly"] + mg),
        "rules_year": tax.rules_year(year),
    }


def pre65_table(ages: list[int], magi: float, household_size: int = 1, medicaid_limit: float | None = None) -> list[dict]:
    """ACA net premium (benchmark minus credit) for one enrollee at each age, given MAGI."""
    out = []
    for a in ages:
        bench = aca.benchmark_annual([a])
        r = aca.premium(magi, household_size, bench, medicaid_limit=medicaid_limit)
        out.append({"age": a, "benchmark": bench, "credit": r["credit"], "net": r["net"], "over_cliff": r["over_cliff"]})
    return out


def hsa_projection(
    balance: float, family: bool, age_now: float, retire_age: float, end_age: float, year: int, growth: float = 0.04, medical_spend: float = 0.0
) -> list[dict]:
    """Real-dollar HSA: max contributions until retirement (or 65, when HSA eligibility ends with Medicare), then medical spending out tax-free."""
    rows, bal = [], max(balance, 0.0)
    for k in range(int(end_age - age_now) + 1):
        age = age_now + k
        contrib = float(hsa.annual_limit(year + k, family, age)) if age < min(retire_age, 65) else 0.0
        bal = bal * (1 + growth) + contrib
        spend = min(bal, medical_spend) if age >= retire_age else 0.0
        bal -= spend
        rows.append({"age": age, "contribution": contrib, "medical_spend": spend, "balance": bal})
    return rows


def ltc_event(mode: str, annual_cost: float, years: float, probability: float | None = None) -> dict:
    """Expected-value (probability x cost) or stress (full cost, certain) long-term-care outlay, per year and total."""
    if mode not in LTC_MODES:
        raise ValueError(f"mode must be one of {LTC_MODES}")
    p = (probability if probability is not None else _data()["ltc"]["probability"]) if mode == "EXPECTED" else 1.0
    p = min(max(p, 0.0), 1.0)
    return {"mode": mode, "probability": p, "annual_cost": annual_cost, "years": years, "annual_expected": annual_cost * p, "total": annual_cost * p * years}


def plan(magi: float, status: str, year: int, people: int, ages: list[int], ltc_cost: float, ltc_years: float) -> dict:
    return {
        "medicare": medicare_cost(magi, status, year, people),
        "pre65": pre65_table(ages, magi, people),
        "ltc": [ltc_event(m, ltc_cost, ltc_years) for m in LTC_MODES],
        "assumptions": _data()["ltc"] | {"verified": _data()["verified"], "source_url": _data()["source_url"], "retrieved_on": retrieved_on()},
        "notes": _data()["notes"],
    }
