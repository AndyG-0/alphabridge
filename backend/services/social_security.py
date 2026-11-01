"""Social Security claiming math: PIA from AIME, claim-age adjustments, spousal and survivor benefits, the earnings test,
break-even ages and a longevity-weighted household NPV across claim-age pairs. Pure functions over data/social_security.json.

Dollars are real (today's) dollars, so COLA is zero in real terms; a benefit-cut haircut can be applied from a chosen year.
Simplifications (also returned with the grid): independent lives with Gompertz survival, a survivor takes the larger of their
own benefit and the survivor benefit, the earnings test is applied to whole calendar years, divorce/child benefits are not modeled."""

import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[1] / "data" / "social_security.json"
CLAIM_AGES = [float(a) for a in range(62, 71)]


@lru_cache(maxsize=1)
def rules() -> dict:
    return json.loads(DATA.read_text())


def retrieved_on() -> date:
    return date.fromisoformat(rules()["retrieved_on"])


def fra_age(birth_year: int) -> float:
    t = {int(k): v for k, v in rules()["full_retirement_age_months"].items()}
    if birth_year in t:
        return t[birth_year] / 12
    if birth_year < min(t):
        return 65.0
    return (t[max(y for y in t if y <= birth_year)] if birth_year < 1960 else t[1960]) / 12


def pia_from_aime(aime: float) -> float:
    """Primary insurance amount (monthly, floored to the dime like SSA) from average indexed monthly earnings."""
    r = rules()
    b1, b2 = r["bend_points"]
    f1, f2, f3 = r["pia_factors"]
    a = max(aime, 0.0)
    pia = f1 * min(a, b1) + f2 * max(min(a, b2) - b1, 0.0) + f3 * max(a - b2, 0.0)
    return math.floor(pia * 10) / 10


def adjustment(claim_age: float, fra: float = 67.0) -> float:
    """Own-benefit multiple vs the full-retirement-age amount (reduced early, +2/3% a month delayed to 70)."""
    claim_age = min(max(claim_age, 62.0), 70.0)
    months = round((claim_age - fra) * 12)
    r = rules()
    if months >= 0:
        return 1 + months * r["delayed_credit_per_month"]
    early = -months
    e = r["early_reduction_per_month"]
    return 1 - (min(early, 36) * e["first_36"] + max(early - 36, 0) * e["beyond"])


def own_benefit(pia: float, claim_age: float, fra: float = 67.0) -> float:
    return pia * adjustment(claim_age, fra)


def spousal_top_up(worker_pia: float, own_pia: float, claim_age: float, fra: float = 67.0) -> float:
    """Extra monthly amount on top of the claimant's own benefit from the spouse's record (50% of their PIA, less own PIA, reduced
    for claiming before the claimant's FRA; delayed credits do not apply to spousal benefits)."""
    r = rules()["spousal"]
    excess = max(r["share_of_worker_pia"] * worker_pia - own_pia, 0.0)
    months_early = max(round((fra - min(max(claim_age, 62.0), fra)) * 12), 0)
    cut = min(months_early, 36) * r["reduction_first_36"] + max(months_early - 36, 0) * r["reduction_beyond"]
    return excess * max(1 - cut, 0.0)


def survivor_benefit(worker_pia: float, worker_claim_age: float, worker_fra: float, survivor_claim_age: float, survivor_fra: float) -> float:
    """Monthly survivor benefit: the deceased's benefit (floored at 82.5% of PIA when they claimed early), reduced linearly from
    100% at the survivor's FRA to 71.5% at 60."""
    r = rules()["survivor"]
    base = own_benefit(worker_pia, worker_claim_age, worker_fra)
    if worker_claim_age < worker_fra:
        base = max(base, r["early_claim_worker_floor"] * worker_pia)
    age = min(max(survivor_claim_age, r["earliest_age"]), survivor_fra)
    span = survivor_fra - r["earliest_age"]
    frac = 1.0 if span <= 0 else r["floor_at_earliest_age"] + (1 - r["floor_at_earliest_age"]) * (age - r["earliest_age"]) / span
    return base * frac


def earnings_test_withheld(annual_benefit: float, earnings: float, age_at_year_start: float, fra: float) -> float:
    """Benefits withheld in a calendar year for work income before FRA (whole-year approximation)."""
    r = rules()["earnings_test"]
    if age_at_year_start >= fra:
        return 0.0
    if age_at_year_start + 1 > fra:  # the year FRA is reached
        over = max(earnings - r["fra_year_exempt"], 0.0) * r["fra_year_withheld_per_dollar"]
    else:
        over = max(earnings - r["under_fra_exempt"], 0.0) * r["under_fra_withheld_per_dollar"]
    return min(over, annual_benefit)


def survival(age: float, now_age: float, modal: float, dispersion: float) -> float:
    """P(alive at `age` | alive at `now_age`) under a Gompertz law with modal age and dispersion (years)."""
    if age <= now_age:
        return 1.0

    def s(a):
        return math.exp(math.exp(-modal / dispersion) * (1 - math.exp(a / dispersion)))

    return s(age) / s(now_age)


def breakeven_age(pia: float, early_claim: float, late_claim: float, fra: float = 67.0) -> float | None:
    """Age at which cumulative (undiscounted) benefits from claiming later catch up with claiming earlier."""
    if late_claim <= early_claim:
        return None
    e, lt = own_benefit(pia, early_claim, fra), own_benefit(pia, late_claim, fra)
    if lt <= e:
        return None
    return (lt * late_claim - e * early_claim) / (lt - e)


def _monthly(person: dict, other: dict | None, claim: float, other_claim: float | None, age: float, other_age: float) -> float:
    """Own benefit plus any spousal top-up (once the spouse has also claimed) for one alive person."""
    if age < claim:
        return 0.0
    amt = own_benefit(person["pia"], claim, person["fra"])
    if other is not None and other_claim is not None and other_age >= other_claim:
        amt += spousal_top_up(other["pia"], person["pia"], claim, person["fra"])
    return amt


def household_npv(
    a: dict,
    b: dict | None,
    claim_a: float,
    claim_b: float | None,
    *,
    real_rate: float = 0.02,
    modal: float = 88.0,
    dispersion: float = 10.0,
    haircut: float = 0.0,
    haircut_year: int | None = None,
    this_year: int | None = None,
    horizon_age: float = 105.0,
) -> float:
    """Expected present value of household Social Security (real dollars) with independent lives, spousal top-ups and survivor benefits."""
    this_year = this_year or date.today().year
    pa = {**a, "fra": fra_age(a["birth_year"])}
    pb = {**b, "fra": fra_age(b["birth_year"])} if b else None
    n = int(horizon_age - min(a["age_now"], b["age_now"] if b else a["age_now"]))
    total = 0.0
    for t in range(n + 1):
        age_a = a["age_now"] + t
        la = survival(age_a, a["age_now"], modal, dispersion)
        cut = 1 - haircut if (haircut and haircut_year is not None and this_year + t >= haircut_year) else 1.0
        if pb is None or b is None or claim_b is None:
            month = la * _monthly(pa, None, claim_a, None, age_a, 0.0)
        else:
            age_b = b["age_now"] + t
            lb = survival(age_b, b["age_now"], modal, dispersion)
            ba = _monthly(pa, pb, claim_a, claim_b, age_a, age_b)
            bb = _monthly(pb, pa, claim_b, claim_a, age_b, age_a)
            surv_a = survivor_benefit(pb["pia"], claim_b, pb["fra"], max(claim_a, 60.0), pa["fra"]) if age_a >= 60 else 0.0
            surv_b = survivor_benefit(pa["pia"], claim_a, pa["fra"], max(claim_b, 60.0), pb["fra"]) if age_b >= 60 else 0.0
            month = la * lb * (ba + bb) + la * (1 - lb) * max(ba, surv_a) + lb * (1 - la) * max(bb, surv_b)
        total += month * 12 * cut / (1 + real_rate) ** t
    return total


def grid(
    a: dict,
    b: dict | None = None,
    *,
    real_rate: float = 0.02,
    modal: float = 88.0,
    dispersion: float = 10.0,
    haircut: float = 0.0,
    haircut_year: int | None = None,
) -> dict:
    """Claim-age grid 62-70 per person, break-even ages and the household NPV across claim-age pairs."""
    kw: dict[str, Any] = dict(real_rate=real_rate, modal=modal, dispersion=dispersion, haircut=haircut, haircut_year=haircut_year)
    people = []
    for p in (a, b):
        if not p:
            continue
        fra = fra_age(p["birth_year"])
        rows = [
            {
                "claim_age": c,
                "monthly": own_benefit(p["pia"], c, fra),
                "factor": adjustment(c, fra),
                "breakeven_vs_67": breakeven_age(p["pia"], c, 67.0, fra) if c < 67 else None,
                "breakeven_vs_62": breakeven_age(p["pia"], 62.0, c, fra) if c > 62 else None,
            }
            for c in CLAIM_AGES
        ]
        people.append({"name": p["name"], "pia": p["pia"], "fra": fra, "claim_age": p["claim_age"], "rows": rows})
    pairs: list[dict[str, Any]] = [
        {"claim_a": ca, "claim_b": cb, "npv": household_npv(a, b, ca, cb, **kw)} for ca in CLAIM_AGES for cb in (CLAIM_AGES if b else [None])
    ]
    best = max(pairs, key=lambda x: x["npv"])
    current = household_npv(a, b, a["claim_age"], b["claim_age"] if b else None, **kw)
    return {
        "people": people,
        "pairs": pairs,
        "best": best,
        "current": {"claim_a": a["claim_age"], "claim_b": b["claim_age"] if b else None, "npv": current},
        "gain_vs_current": best["npv"] - current,
        "assumptions": [
            f"Gompertz survival, modal age {modal:g}, dispersion {dispersion:g}; independent lives; real discount rate {real_rate:.1%}.",
            "Real dollars, so the COLA is zero in real terms." + (f" Benefits cut {haircut:.0%} from {haircut_year}." if haircut else ""),
            "The entered benefit is treated as the full-retirement-age amount (PIA).",
            "A surviving spouse receives the larger of their own and the survivor benefit; child and divorced-spouse benefits are not modeled.",
            "Break-even ages are undiscounted cumulative benefits.",
        ],
        "rules_year": rules()["year"],
        "retrieved_on": rules()["retrieved_on"],
    }
