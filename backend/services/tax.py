"""Deterministic federal + state tax engine. Tables live in data/tax_tables/<year>.json (IRS / CMS) and
data/state_income_tax.json; nothing here is an inline constant. Filing status is SINGLE or MFJ.

Simplifications (see docs once E13 lands): standard deduction only, no credits, no AMT, no above-the-line
adjustments beyond what the caller folds into `ordinary`, state tax is flat-rate on federal-style taxable income."""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TABLE_DIR = DATA_DIR / "tax_tables"
STATE_FILE = DATA_DIR / "state_income_tax.json"
STATUSES = ("SINGLE", "MFJ")


@lru_cache(maxsize=1)
def _tables() -> dict[int, dict[str, Any]]:
    return {int(p.stem): json.loads(p.read_text()) for p in sorted(TABLE_DIR.glob("*.json"))}


@lru_cache(maxsize=1)
def _states() -> dict[str, Any]:
    return json.loads(STATE_FILE.read_text())


def table_years() -> list[int]:
    return sorted(_tables())


def rules_year(year: int) -> int:
    """Year of the table used for `year`: the nearest known year (we never extrapolate indexing)."""
    years = table_years()
    return min(max(year, years[0]), years[-1])


def table(year: int) -> dict[str, Any]:
    return _tables()[rules_year(year)]


def retrieved_on() -> date:
    """Retrieval date of the newest federal table (the staleness test keys off this)."""
    return date.fromisoformat(table(table_years()[-1])["retrieved_on"])


def _status(status: str | None) -> str:
    s = (status or "SINGLE").upper()
    return s if s in STATUSES else "SINGLE"


def standard_deduction(status: str, year: int) -> float:
    return float(table(year)["standard_deduction"][_status(status)])


def _brackets(status: str, year: int) -> list[tuple[float, float]]:
    return [(float(lo), float(r)) for lo, r in table(year)["ordinary_brackets"][_status(status)]]


def ordinary_tax(taxable: float, status: str, year: int) -> tuple[float, float]:
    """(tax, marginal rate) on ordinary taxable income."""
    taxable = max(taxable, 0.0)
    br = _brackets(status, year)
    tax, marginal = 0.0, br[0][1]
    for i, (lo, rate) in enumerate(br):
        hi = br[i + 1][0] if i + 1 < len(br) else float("inf")
        if taxable > lo:
            tax += (min(taxable, hi) - lo) * rate
            marginal = rate
    return tax, marginal


def ltcg_tax(gains: float, ordinary_taxable: float, status: str, year: int) -> float:
    """Tax on qualified gains/dividends stacked on top of ordinary taxable income (0/15/20% bands)."""
    gains = max(gains, 0.0)
    cfg = table(year)["ltcg"]
    zero_top, fifteen_top = float(cfg[_status(status)]["zero_up_to"]), float(cfg[_status(status)]["fifteen_up_to"])
    r0, r15, r20 = cfg["rates"]
    start = max(ordinary_taxable, 0.0)
    end = start + gains
    at0 = max(min(end, zero_top) - start, 0.0)
    at15 = max(min(end, fifteen_top) - max(start, zero_top), 0.0)
    at20 = gains - at0 - at15
    return at0 * r0 + at15 * r15 + at20 * r20


def taxable_social_security(benefits: float, other_income: float, status: str, year: int, tax_exempt_interest: float = 0.0) -> float:
    """Taxable part of Social Security via the provisional-income tiers (IRS Pub 915 worksheet)."""
    benefits = max(benefits, 0.0)
    if benefits == 0:
        return 0.0
    cfg = table(year)["social_security"]
    s = _status(status)
    base, add = float(cfg["base"][s]), float(cfg["additional"][s])
    share1, cap = float(cfg["first_tier_share"]), float(cfg["max_share"])
    provisional = other_income + tax_exempt_interest + share1 * benefits
    if provisional <= base:
        return 0.0
    tier1 = share1 * min(provisional - base, add - base)
    tier2 = cap * max(provisional - add, 0.0)
    return min(tier1 + tier2, cap * benefits)


def niit(net_investment_income: float, magi: float, status: str, year: int) -> float:
    cfg = table(year)["niit"]
    excess = max(magi - float(cfg["threshold"][_status(status)]), 0.0)
    return float(cfg["rate"]) * min(max(net_investment_income, 0.0), excess)


def irmaa(magi: float, status: str, year: int) -> dict[str, Any]:
    """IRMAA tier (0 = no surcharge) with monthly Part B / Part D surcharges per person."""
    cfg = table(year)["irmaa"]
    tier, b, d = 0, 0.0, 0.0
    for i, (over, part_b, part_d) in enumerate(cfg["tiers"][_status(status)], start=1):
        if magi > over:
            tier, b, d = i, float(part_b), float(part_d)
    return {"tier": tier, "part_b_surcharge_monthly": b, "part_d_surcharge_monthly": d, "part_b_total_monthly": float(cfg["base_part_b_monthly"]) + b}


def state_rule(state: str | None) -> dict[str, Any]:
    d = _states()
    code = (state or "").upper()
    if code in d["states"]:
        return {**d["states"][code], "state": code, "known": True}
    return {"flat_rate": d["default_flat_rate"], "taxes_social_security": d["default_taxes_social_security"], "state": code, "known": False}


def state_tax(taxable: float, state: str | None, flat_rate: float | None = None) -> float:
    """Flat-rate state income tax; `flat_rate` overrides the table (user-configurable)."""
    rate = state_rule(state)["flat_rate"] if flat_rate is None else flat_rate
    return max(taxable, 0.0) * rate


def total_tax(
    *,
    ordinary: float,
    qualified: float = 0.0,
    social_security: float = 0.0,
    status: str = "SINGLE",
    year: int,
    state: str | None = None,
    state_flat_rate: float | None = None,
) -> dict[str, Any]:
    """Full-year estimate. `ordinary` excludes Social Security and qualified gains/dividends; `qualified` is LTCG + qualified dividends."""
    s = _status(status)
    ss_taxable = taxable_social_security(social_security, ordinary + qualified, s, year)
    agi = ordinary + qualified + ss_taxable
    taxable_ordinary = max(ordinary + ss_taxable - standard_deduction(s, year), 0.0)
    # Unused standard deduction shelters qualified income too.
    spare_deduction = max(standard_deduction(s, year) - (ordinary + ss_taxable), 0.0)
    taxable_qualified = max(qualified - spare_deduction, 0.0)
    ord_tax, marginal = ordinary_tax(taxable_ordinary, s, year)
    cg_tax = ltcg_tax(taxable_qualified, taxable_ordinary, s, year)
    nii_tax = niit(qualified, agi, s, year)
    rule = state_rule(state)
    state_base = max(agi - (ss_taxable if not rule["taxes_social_security"] else 0.0) - standard_deduction(s, year), 0.0)
    st_tax = state_tax(state_base, state, state_flat_rate)
    federal = ord_tax + cg_tax + nii_tax
    total = federal + st_tax
    gross = ordinary + qualified + social_security
    st_rate = rule["flat_rate"] if state_flat_rate is None else state_flat_rate
    return {
        "rules_year": rules_year(year),
        "filing_status": s,
        "agi": agi,
        "taxable_social_security": ss_taxable,
        "taxable_income": taxable_ordinary + taxable_qualified,
        "federal_ordinary": ord_tax,
        "federal_capital_gains": cg_tax,
        "niit": nii_tax,
        "federal": federal,
        "state": st_tax,
        "state_known": rule["known"],
        "total": total,
        "effective_rate": total / gross if gross > 0 else 0.0,
        "marginal_rate": marginal + (st_rate if st_tax > 0 or state_base > 0 else 0.0),
        "marginal_federal_rate": marginal,
        "irmaa": irmaa(agi, s, year),
    }


def effective_rate_estimate(income: float, status: str, year: int, state: str | None = None) -> float:
    """Blended rate on wage-like income; used where the app previously assumed a flat `effective_tax_rate`."""
    return float(total_tax(ordinary=income, status=status, year=year, state=state)["effective_rate"])
