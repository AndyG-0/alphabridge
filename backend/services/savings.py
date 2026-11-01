"""Savings and accumulation: contribution limits, match capture, waterfall, FI variants.

Pure functions; limits come from data/contribution_limits.json (IRS Notice 2025-67) and data/hsa_limits.json.
"""

import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

from services import hsa

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "contribution_limits.json"
SUPER_CATCH_UP_AGES = (60, 63)


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA_FILE.read_text())


def retrieved_on() -> date:
    return date.fromisoformat(_data()["retrieved_on"])


def rules_year(year: int) -> int:
    ys = sorted(int(y) for y in _data()["years"])
    return min(max(year, ys[0]), ys[-1])


def _row(year: int) -> dict:
    return _data()["years"][str(rules_year(year))]


def _phase_out(magi: float, lo: float, hi: float, full: float, floor: float = 0.0) -> float:
    """Allowed amount after a linear phase-out; reduction rounds up to $10, with a $200 floor while a reduction applies."""
    if magi <= lo:
        return full
    if magi >= hi:
        return 0.0
    left = full * (hi - magi) / (hi - lo)
    left = math.ceil(left / 10.0) * 10.0
    return min(full, max(left, floor or 200.0))


def limits(
    year: int, age: float, status: str = "SINGLE", magi: float = 0.0, covered_by_plan: bool = True, spouse_covered: bool = False, wages_prior_year: float = 0.0
) -> dict:
    """Every contribution limit that applies to one person in `year`, with the age-based catch-ups resolved."""
    r = _row(year)
    lo, hi = SUPER_CATCH_UP_AGES
    if lo <= age <= hi:
        catch, simple_catch, kind = r["k401_super_catch_up_60_63"], r["simple_super_catch_up_60_63"], "super"
    elif age >= 50:
        catch, simple_catch, kind = r["k401_catch_up_50"], r["simple_catch_up_50"], "standard"
    else:
        catch, simple_catch, kind = 0, 0, "none"
    ira_base = r["ira"] + (r["ira_catch_up_50"] if age >= 50 else 0)
    ro = r["roth_ira_phase_out"][status if status in r["roth_ira_phase_out"] else "SINGLE"]
    roth_ira = _phase_out(magi, ro[0], ro[1], ira_base)
    ded = r["ira_deduction_phase_out"]
    if not covered_by_plan and not (status == "MFJ" and spouse_covered):
        deductible = ira_base
    elif covered_by_plan:
        w = ded["MFJ_COVERED"] if status == "MFJ" else ded["SINGLE_COVERED"]
        deductible = _phase_out(magi, w[0], w[1], ira_base)
    else:
        w = ded["MFJ_SPOUSE_COVERED"]
        deductible = _phase_out(magi, w[0], w[1], ira_base)
    return {
        "year": year,
        "rules_year": rules_year(year),
        "k401_deferral": r["k401_deferral"],
        "k401_catch_up": catch,
        "k401_catch_up_kind": kind,
        "k401_max": r["k401_deferral"] + catch,
        "simple_max": r["simple"] + simple_catch,
        "ira_base": ira_base,
        "roth_ira_allowed": roth_ira,
        "roth_ira_direct_ok": roth_ira >= ira_base,
        "ira_deductible": deductible,
        "section_415c": r["section_415c"],
        "compensation_limit": r["compensation_limit_401a17"],
        "roth_catch_up_required": bool(catch and wages_prior_year > r["roth_catch_up_wage_threshold"]),
        "hsa_self_only": hsa.annual_limit(year, False, age),
        "hsa_family": hsa.annual_limit(year, True, age),
    }


def match_capture(salary: float, deferral: float, match_rate: float, match_cap_pct: float) -> dict:
    """Employer match: `match_rate` per $1 deferred, on deferrals up to `match_cap_pct` of pay (e.g. 50% of the first 6%)."""
    salary, deferral = max(salary, 0.0), max(deferral, 0.0)
    eligible = salary * max(match_cap_pct, 0.0)
    max_match = eligible * match_rate
    got = min(deferral, eligible) * match_rate
    return {
        "max_match": max_match,
        "captured": got,
        "left_on_table": max_match - got,
        "deferral_to_capture_all": eligible,
        "fully_captured": got >= max_match - 1e-9,
    }


def waterfall(
    surplus: float,
    salary: float,
    age: float,
    year: int,
    status: str = "SINGLE",
    magi: float | None = None,
    match_rate: float = 0.0,
    match_cap_pct: float = 0.0,
    hsa_eligible: bool = False,
    hsa_family: bool = False,
    employer_contrib: float = 0.0,
    prefer_roth_401k: bool = False,
    mega_backdoor: bool = False,
    covered_by_plan: bool = True,
) -> dict:
    """Allocate annual savings in order: 401(k) match -> HSA -> Roth/IRA -> rest of 401(k) -> (optional mega-backdoor) -> taxable."""
    lim = limits(year, age, status, magi if magi is not None else salary, covered_by_plan)
    left = max(surplus, 0.0)
    steps: list[dict] = []

    def put(name: str, room: float, why: str) -> float:
        nonlocal left
        amt = max(0.0, min(left, room))
        steps.append({"step": name, "amount": amt, "room": max(room, 0.0), "why": why})
        left -= amt
        return amt

    mc = match_capture(salary, 0.0, match_rate, match_cap_pct)
    cap_room = min(mc["deferral_to_capture_all"], lim["k401_max"]) if match_rate > 0 else 0.0
    k401 = put("401(k) up to the employer match", cap_room, "An immediate return equal to the match rate; nothing beats it.")
    if hsa_eligible:
        put(
            "HSA",
            lim["hsa_family" if hsa_family else "hsa_self_only"],
            "Triple tax-advantaged when spent on medical costs; invest it and pay current bills from cash.",
        )
    ira_room = lim["roth_ira_allowed"]
    if ira_room > 0:
        put("Roth IRA", ira_room, "Tax-free growth and penalty-free basis access before 59 1/2.")
    else:
        put("Non-deductible IRA + backdoor Roth", lim["ira_base"], "Above the direct Roth limit: use the backdoor checklist.")
    k401 += put(
        "401(k) / 403(b) " + ("Roth" if prefer_roth_401k else "pre-tax") + " up to the limit", lim["k401_max"] - k401, "Remaining employee deferral room."
    )
    if mega_backdoor:
        room = lim["section_415c"] + (lim["k401_catch_up"]) - k401 - employer_contrib
        put("After-tax 401(k) -> Roth (mega-backdoor)", room, "Needs a plan that allows after-tax contributions and in-service conversions.")
    put("Taxable brokerage", left, "Flexible; hold tax-efficient index funds.")
    return {"steps": steps, "unallocated": left, "limits": lim, "match": mc}


def backdoor_checklist(pretax_ira_balance: float, plan_allows_after_tax: bool, plan_allows_in_service: bool) -> dict:
    pro_rata = pretax_ira_balance > 0
    return {
        "backdoor_roth": [
            {"step": "Contribute to a non-deductible traditional IRA (Form 8606 basis)", "ok": True},
            {"step": "Convert to Roth promptly, before gains accrue", "ok": True},
            {
                "step": "No pre-tax IRA balances, or the pro-rata rule taxes most of the conversion",
                "ok": not pro_rata,
                "note": f"${pretax_ira_balance:,.0f} pre-tax IRA balance. Roll it into a 401(k) first." if pro_rata else "",
            },
            {"step": "File Form 8606 every year", "ok": True},
        ],
        "mega_backdoor_roth": [
            {"step": "Plan allows after-tax (non-Roth) employee contributions", "ok": plan_allows_after_tax},
            {"step": "Plan allows in-service conversion or withdrawal to a Roth", "ok": plan_allows_in_service},
            {"step": "Total additions stay under the 415(c) limit including the match", "ok": True},
        ],
        "backdoor_viable": not pro_rata,
        "mega_backdoor_viable": plan_allows_after_tax and plan_allows_in_service,
    }


def fi_number(annual_spend: float, withdrawal_rate: float = 0.04) -> float:
    return annual_spend / withdrawal_rate if withdrawal_rate > 0 else math.inf


def coast_number(fi: float, years: float, real_return: float) -> float:
    """Balance today that grows to `fi` with no more contributions."""
    return fi / (1.0 + real_return) ** max(years, 0.0)


def years_to_target(balance: float, annual_saving: float, target: float, real_return: float, cap: int = 80) -> float | None:
    """Years until balance (contributing at year end) reaches `target`, solved in closed form; None if unreachable within `cap`."""
    if balance >= target:
        return 0.0
    r = real_return
    if abs(r) < 1e-12:
        n = (target - balance) / annual_saving if annual_saving > 0 else math.inf
    else:
        num = target * r + annual_saving
        den = balance * r + annual_saving
        if den <= 0 or num <= 0 or num / den <= 1.0:
            return None
        n = math.log(num / den) / math.log(1.0 + r)
    return n if n <= cap else None


def fi_variants(
    annual_spend: float,
    balance: float,
    annual_saving: float,
    age: float,
    retire_age: float,
    real_return: float = 0.05,
    withdrawal_rate: float = 0.04,
    part_time_income: float = 0.0,
    fat_multiplier: float = 1.5,
    lean_multiplier: float = 0.6,
) -> dict:
    fi = fi_number(annual_spend, withdrawal_rate)
    variants = {
        "lean": fi_number(annual_spend * lean_multiplier, withdrawal_rate),
        "fi": fi,
        "fat": fi_number(annual_spend * fat_multiplier, withdrawal_rate),
        "barista": fi_number(max(annual_spend - part_time_income, 0.0), withdrawal_rate),
    }
    coast = coast_number(fi, retire_age - age, real_return)
    out = {
        "withdrawal_rate": withdrawal_rate,
        "real_return": real_return,
        "annual_spend": annual_spend,
        "numbers": variants,
        "coast": {"needed_now": coast, "reached": balance >= coast, "years_to_coast": years_to_target(balance, annual_saving, coast, real_return)},
        "progress": {k: (balance / v if v else 1.0) for k, v in variants.items()},
        "years_to": {k: years_to_target(balance, annual_saving, v, real_return) for k, v in variants.items()},
    }
    out["sensitivity"] = sensitivity(annual_spend, balance, annual_saving, real_return, withdrawal_rate)
    return out


def sensitivity(annual_spend: float, balance: float, annual_saving: float, real_return: float, withdrawal_rate: float) -> list[dict]:
    """Years to FI across return and savings changes (the 'what moves the date' table)."""
    fi = fi_number(annual_spend, withdrawal_rate)
    return [
        {"return": real_return + dr, "saving_change": ds, "years": years_to_target(balance, annual_saving * (1 + ds), fi, real_return + dr)}
        for dr in (-0.02, 0.0, 0.02)
        for ds in (-0.2, 0.0, 0.2)
    ]
