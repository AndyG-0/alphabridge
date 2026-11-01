"""Required minimum distributions and QCDs (SECURE 2.0). Tables live in data/rmd_tables.json (IRS Pub 590-B, Notice 2025-67).

Pure math, no I/O. Amounts are in the caller's dollars; `balance` is the prior Dec 31 balance. The Table II joint-life divisor
(spouse sole beneficiary more than 10 years younger) is not tabulated: `joint_life_applies` flags that case so callers can warn,
and the Uniform table is used, which overstates the RMD slightly."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from services import tax as tax_svc

DATA = Path(__file__).resolve().parents[1] / "data" / "rmd_tables.json"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(DATA.read_text())


def retrieved_on() -> str:
    return _data()["retrieved_on"]


def start_age(birth_year: int) -> int:
    for rule in _data()["start_age_rules"]:
        if birth_year <= rule["born_through"]:
            return int(rule["age"])
    return 75


def uniform_divisor(age: int) -> float | None:
    """Table III divisor; None below 72 (no distribution is computed by the table)."""
    t = _data()["uniform_lifetime"]
    return None if age < 72 else float(t[str(min(age, 120))])


def single_life_divisor(age: int) -> float:
    return float(_data()["single_life"][str(min(max(age, 0), 120))])


def joint_life_applies(owner_age: int, spouse_age: int | None, spouse_sole_beneficiary: bool) -> bool:
    return bool(spouse_sole_beneficiary and spouse_age is not None and owner_age - spouse_age > 10)


def rmd(balance: float, age: int) -> float:
    d = uniform_divisor(age)
    return 0.0 if d is None or balance <= 0 else balance / d


def qcd_limit(year: int) -> float:
    lim = _data()["qcd"]["limits"]
    return float(lim.get(str(year), lim[max(lim)]))  # not indexed forward: the newest known year


def qcd_eligible(age: float) -> bool:
    return age >= _data()["qcd"]["min_age"]


def projection(
    balance: float,
    birth_year: int,
    start_year: int,
    *,
    real_return: float = 0.03,
    end_age: int = 95,
    qcd_annual: float = 0.0,
    spouse_age_now: int | None = None,
    spouse_sole_beneficiary: bool = False,
    age_now: int | None = None,
) -> dict[str, Any]:
    """Pre-tax balance and RMD by year from `start_year` (balance as of Dec 31 of the prior year). QCDs satisfy the RMD first and are
    capped by the annual limit, the RMD itself and age 70½."""
    first = start_age(birth_year)
    rows = []
    bal = balance
    joint = age_now is not None and joint_life_applies(age_now, spouse_age_now, spouse_sole_beneficiary)
    for year in range(start_year, birth_year + end_age + 1):
        age = year - birth_year
        req = rmd(bal, age) if age >= first else 0.0
        qcd = min(qcd_annual, qcd_limit(year), bal) if qcd_eligible(age) and qcd_annual > 0 else 0.0
        qcd_used = min(qcd, req) if req > 0 else qcd  # a QCD before RMD age still lowers the balance but offsets nothing
        taxable_rmd = max(req - qcd_used, 0.0)
        draw = max(req, qcd)
        rows.append(
            {
                "year": year,
                "age": age,
                "start_balance": bal,
                "rmd": req,
                "qcd": qcd,
                "taxable_rmd": taxable_rmd,
                "end_balance": max(bal - draw, 0.0) * (1 + real_return),
            }
        )
        bal = rows[-1]["end_balance"]
    return {"start_age": first, "rows": rows, "joint_life_table_would_apply": joint, "source_url": _data()["source_url"], "retrieved_on": retrieved_on()}


def inherited_schedule(
    balance: float,
    beneficiary_age: int,
    death_year: int,
    owner_died_on_or_after_rbd: bool,
    *,
    real_return: float = 0.03,
    eligible_designated: bool = False,
) -> dict[str, Any]:
    """Inherited-account distributions. Non-eligible beneficiaries: empty by Dec 31 of the 10th year after death; if the owner had already
    reached their required beginning date, annual RMDs on the beneficiary's single-life divisor are also due in years 1-9. Eligible designated
    beneficiaries (spouse, minor child, disabled/chronically ill, not >10 years younger) may stretch over single-life expectancy."""
    rows = []
    bal = balance
    limit = _data()["inherited"]["ten_year_rule_years"]
    for i in range(1, 60 if eligible_designated else limit + 1):
        year = death_year + i
        age = beneficiary_age + i
        if eligible_designated:
            req = bal / max(single_life_divisor(beneficiary_age + 1) - (i - 1), 1.0)
        elif i == limit:
            req = bal
        elif owner_died_on_or_after_rbd:
            req = bal / max(single_life_divisor(beneficiary_age + 1) - (i - 1), 1.0)
        else:
            req = 0.0
        req = min(req, bal)
        rows.append({"year": year, "beneficiary_age": age, "start_balance": bal, "required": req})
        bal = (bal - req) * (1 + real_return)
        if bal <= 1e-6:
            break
    rule = (
        "life-expectancy stretch"
        if eligible_designated
        else "10-year rule" + (" with annual RMDs in years 1-9" if owner_died_on_or_after_rbd else " (no annual RMDs, empty by year 10)")
    )
    return {"rule": rule, "rows": rows}


def forced_bracket(rmd_amount: float, other_ordinary: float, social_security: float, status: str, year: int, *, qcd: float = 0.0) -> dict[str, Any]:
    """What an RMD does to the bracket: marginal rate and IRMAA tier with and without it. P3 uses `bracket_jump`/`irmaa_jump` to size conversions earlier."""
    taxable_rmd = max(rmd_amount - qcd, 0.0)
    without = tax_svc.total_tax(ordinary=other_ordinary, social_security=social_security, status=status, year=year)
    with_ = tax_svc.total_tax(ordinary=other_ordinary + taxable_rmd, social_security=social_security, status=status, year=year)
    return {
        "marginal_without": without["marginal_federal_rate"],
        "marginal_with": with_["marginal_federal_rate"],
        "bracket_jump": with_["marginal_federal_rate"] > without["marginal_federal_rate"] + 1e-9,
        "irmaa_tier_without": without["irmaa"]["tier"],
        "irmaa_tier_with": with_["irmaa"]["tier"],
        "irmaa_jump": with_["irmaa"]["tier"] > without["irmaa"]["tier"],
        "extra_tax": with_["total"] - without["total"],
        "taxable_social_security_added": with_["taxable_social_security"] - without["taxable_social_security"],
    }
