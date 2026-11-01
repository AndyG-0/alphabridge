"""Survivor and estate planning (P15): death-of-spouse income and tax, estate-tax exposure, beneficiary audit, insurance gaps.

Pure math. Constants come from data/estate.json (with a source URL and a `verified` flag). Taxes go through `tax.total_tax`; survivor Social
Security uses the P5 rules in `services.social_security`."""

import json
from functools import lru_cache
from pathlib import Path

from services import social_security as ss
from services import tax

DATA = Path(__file__).resolve().parents[1] / "data" / "estate.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text())


def defaults() -> dict:
    return dict(_data())


def estate_exposure(net_worth: float, married: bool, portability: bool = True) -> dict:
    """Federal estate tax if the estate is `net_worth`. A married couple with portability shelters two exclusions; without it only one."""
    d = _data()
    shelter = d["basic_exclusion"] * (2 if married and portability else 1)
    excess = max(net_worth - shelter, 0.0)
    flag = "OVER" if excess > 0 else "WATCH" if net_worth >= d["watch_fraction"] * shelter else "OK"
    return {
        "net_worth": net_worth,
        "exclusion": shelter,
        "taxable_estate": excess,
        "estimated_tax": excess * d["top_rate"],
        "flag": flag,
        "headroom": shelter - net_worth,
        "portability_assumed": bool(married and portability),
    }


def survivor_social_security(
    deceased_ss_67: float, survivor_ss_67: float, deceased_claim: float, survivor_claim: float, deceased_fra: float = 67.0, survivor_fra: float = 67.0
) -> dict:
    """Monthly Social Security after one death: the survivor keeps the larger of their own benefit and the survivor benefit."""
    own = ss.own_benefit(survivor_ss_67, survivor_claim, survivor_fra)
    widow = ss.survivor_benefit(deceased_ss_67, deceased_claim, deceased_fra, survivor_claim, survivor_fra)
    keep = max(own, widow)
    lost = ss.own_benefit(deceased_ss_67, deceased_claim, deceased_fra)  # the smaller of the two is what actually disappears
    return {"own": own, "survivor_benefit": widow, "household_after": keep, "household_before": own + lost, "monthly_lost": own + lost - keep}


def death_of_spouse(
    *,
    year: int,
    spend: float,
    ss_before_monthly: float,
    ss_after_monthly: float,
    other_ordinary: float,
    pretax_draw: float,
    qualified: float = 0.0,
    spend_ratio: float | None = None,
) -> dict:
    """Same household before (MFJ) and after (single). Ordinary income keeps coming from the pre-tax draw, but the standard deduction and
    brackets halve, so the survivor can pay more tax on less income (the 'widow's penalty')."""
    ratio = _data()["survivor_spend_ratio"] if spend_ratio is None else spend_ratio
    before_ord = other_ordinary + pretax_draw
    t_before = tax.total_tax(ordinary=before_ord, qualified=qualified, social_security=ss_before_monthly * 12, status="MFJ", year=year)
    t_after = tax.total_tax(ordinary=before_ord, qualified=qualified, social_security=ss_after_monthly * 12, status="SINGLE", year=year)
    tb, ta = float(t_before["total"]), float(t_after["total"])
    inc_before = before_ord + qualified + ss_before_monthly * 12
    inc_after = before_ord + qualified + ss_after_monthly * 12
    need_after = spend * ratio
    return {
        "tax_before": tb,
        "tax_after": ta,
        "tax_increase": ta - tb,
        "income_before": inc_before,
        "income_after": inc_after,
        "spend_before": spend,
        "spend_after": need_after,
        "after_tax_surplus_before": inc_before - tb - spend,
        "after_tax_surplus_after": inc_after - ta - need_after,
        "spend_ratio": ratio,
        "widows_penalty": ta > tb,
    }


RETITLE_ITEMS = [
    ("Joint taxable and bank accounts", "Pass by survivorship; confirm titling says JTWROS or TOD so they skip probate."),
    ("Individual IRA / 401(k)", "A spouse beneficiary can roll over as their own; confirm a named primary and contingent beneficiary."),
    ("Roth IRA / Roth 401(k)", "Same rollover option; the survivor's own 5-year clock may already be satisfied."),
    ("HSA", "Passes tax-free to a spouse beneficiary only; to anyone else it becomes taxable income."),
    ("Annuities / pensions", "Check the survivor option elected at the start; a single-life choice ends at death."),
    ("Life insurance", "Confirm the owner, insured and beneficiary lines; an estate beneficiary adds probate."),
    ("Home and vehicles", "Check deed and title form; a step-up in basis applies to the decedent's share."),
]


def beneficiary_audit(accounts: list[dict]) -> dict:
    """A checklist per account. The app does not store beneficiaries, so every item is a prompt to verify, not a finding."""
    rows = [
        {"account": a["name"], "bucket": a.get("bucket", ""), "owner": a.get("owner", ""), "balance": a.get("balance", 0.0),
         "check": "Confirm primary and contingent beneficiaries match your wishes and your will."}
        for a in accounts
    ]  # fmt: skip
    return {"accounts": rows, "retitling": [{"item": i, "note": n} for i, n in RETITLE_ITEMS], "stored": False}


def insurance_gap(
    *,
    income: float,
    debts: float,
    liquid_assets: float,
    existing_life: float,
    group_disability_monthly: float,
    years: int | None = None,
    replace_pct: float | None = None,
) -> dict:
    """Term-life need (income replacement + debts + final expenses, less liquid assets and existing cover) and the disability income gap."""
    d = _data()
    yrs = d["income_replacement_years"] if years is None else years
    pct = d["income_replacement_pct"] if replace_pct is None else replace_pct
    need = income * pct * yrs + debts + d["final_expenses"]
    life_gap = max(need - liquid_assets - existing_life, 0.0)
    target_monthly = income * d["disability_replacement_pct"] / 12
    dis_gap = max(target_monthly - group_disability_monthly, 0.0)
    return {
        "life_need": need,
        "life_gap": life_gap,
        "years": yrs,
        "replace_pct": pct,
        "disability_target_monthly": target_monthly,
        "disability_gap_monthly": dis_gap,
    }
