"""Penalty-free access to retirement money before 59.5 (IRC 72(t)). Pure math, no I/O. Data lives in data/early_access_rules.json."""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from services.age import age_on

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "early_access_rules.json"
PRETAX = "PRE_TAX_401K"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA_FILE.read_text())


def retrieved_on() -> date:
    return date.fromisoformat(_data()["retrieved_on"])


def exceptions() -> list[dict]:
    return _data()["exceptions"]


def penalty_cost(amount: float, marginal_rate: float) -> dict:
    """Tax plus the 10% additional tax on an early distribution of `amount`."""
    amount = max(amount, 0.0)
    tax = amount * marginal_rate
    penalty = amount * _data()["penalty_rate"]
    return {"amount": amount, "income_tax": tax, "penalty": penalty, "net": amount - tax - penalty}


def rule_of_55_eligible(birth_date: date, separation_year: int, current_employer_plan: bool) -> bool:
    """Separating in or after the calendar year you turn 55, and only from that employer's own plan."""
    return current_employer_plan and separation_year >= birth_date.year + _data()["rule_of_55_age"]


SEPP_METHODS = ("amortization", "annuitization", "rmd")
SEPP_TABLES = ("single", "uniform")


def max_sepp_rate(mid_term_rate: float) -> float:
    """Notice 2022-6 sec. 3.02(c): the greater of 5% or 120% of the federal mid-term rate."""
    return max(_data()["sepp_rate_floor_cap"], 1.2 * mid_term_rate)


def annuity_factor(age: int, rate: float) -> float:
    """PV of $1 a year starting now (first payment at `age`) for life, using the mortality rates required by Notice 2022-6 sec. 3.01(c)."""
    q = _data()["mortality_qx"]
    if not 0 <= age < len(q):
        raise ValueError("age out of range for the mortality table")
    v, alive, total = 1 / (1 + rate), 1.0, 0.0
    for a in range(age, len(q)):
        total += alive
        alive *= (1 - q[a]) * v
    return total + alive * v * (1 - q[-1]) / (1 - (1 - q[-1]) * v)  # q stays 40% after 120, so the tail is geometric


def sepp_payment(balance: float, age: int, rate: float, method: str = "amortization", table: str = "single", mid_term_rate: float | None = None) -> dict:
    """Annual 72(t) payment under the RMD, fixed amortization or fixed annuitization method. `rate` must not exceed the
    Notice 2022-6 cap (greater of 5% or 120% of the mid-term rate); pass `mid_term_rate` to have it checked."""
    d = _data()
    single = {int(k): v for k, v in d["single_life"].items()}
    if age not in single:
        raise ValueError(f"age must be between {min(single)} and {max(single)}")
    if balance < 0 or rate < 0:
        raise ValueError("balance and rate must be non-negative")
    if method not in SEPP_METHODS:
        raise ValueError(f"method must be one of {', '.join(SEPP_METHODS)}")
    if table not in SEPP_TABLES:
        raise ValueError(f"table must be one of {', '.join(SEPP_TABLES)}")
    n = single[age] if table == "single" else float(d["uniform_lifetime"][str(age)])
    factor = None
    if method == "rmd":
        pay = balance / n
    elif method == "annuitization":
        factor = annuity_factor(age, rate)
        pay = balance / factor
    else:
        pay = balance / n if rate == 0 else balance * rate / (1 - (1 + rate) ** -n)
    years = max(d["sepp_min_years"], d["normal_age"] - age)
    cap = max_sepp_rate(mid_term_rate) if mid_term_rate is not None else d["sepp_rate_floor_cap"]
    return {
        "method": method,
        "table": "mortality (Treas. Reg. 1.401(a)(9)-9(e))" if method == "annuitization" else table,
        "annual_payment": pay,
        "life_expectancy": n,
        "annuity_factor": factor,
        "years_required": years,
        "ends_at_age": age + years,
        "max_rate": cap,
        "rate_within_cap": rate <= cap + 1e-12,
        "warning": "Changing the payment, adding to or withdrawing extra from the account before the end date triggers the 10% penalty on every payment, plus interest.",  # noqa: E501
    }


def roth_ordering(contributions: float, conversions: list[dict], earnings: float, withdraw: float, age: float, year: int, roth_open_year: int) -> dict:
    """Which Roth dollars a withdrawal consumes (IRC 408A(d)(4)): contributions first, then conversions oldest first, then earnings.
    `conversions` = [{"year", "amount"}]. Converted dollars withdrawn within 5 tax years of the conversion and before 59.5 owe the
    10% additional tax; earnings are taxable and penalized unless the account is 5+ years old and the owner is 59.5+ (or another exception applies)."""
    d = _data()
    penalty_age = d["normal_age"]
    left = max(withdraw, 0.0)
    take_c = min(left, max(contributions, 0.0))
    left -= take_c
    layers, penalty, taxable = [], 0.0, 0.0
    for c in sorted(conversions, key=lambda x: x["year"]):
        take = min(left, max(c["amount"], 0.0))
        if take <= 0:
            continue
        left -= take
        young = year - c["year"] < 5 and age < penalty_age
        penalty += take * d["penalty_rate"] if young else 0.0
        layers.append({"kind": "conversion", "year": c["year"], "amount": take, "penalty": take * d["penalty_rate"] if young else 0.0, "taxable": 0.0})
    take_e = min(left, max(earnings, 0.0))
    left -= take_e
    qualified = year - roth_open_year >= 5 and age >= penalty_age
    if not qualified:
        taxable += take_e
        penalty += take_e * d["penalty_rate"] if age < penalty_age else 0.0
    return {
        "withdrawn": withdraw - left,
        "unfunded": left,
        "from_contributions": take_c,
        "from_conversions": layers,
        "from_earnings": take_e,
        "earnings_qualified": qualified,
        "taxable": taxable,
        "penalty": penalty,
        "order": ["contributions (tax and penalty free)", "conversions, oldest first (penalty if under 5 years old and under 59.5)", "earnings"],
    }


def account_access(account, owner_birth: date | None, retire_age: float, is_current_employer: bool, today: date | None = None) -> dict:
    """Where an account's money can be reached without the 10% penalty."""
    d = _data()
    if account.tax_bucket != PRETAX:
        return {"accessible_at": 0.0, "reason": "Not a retirement-plan balance; no early-withdrawal penalty."}
    if owner_birth is None:
        return {"accessible_at": d["normal_age"], "reason": "No birth date on file; assuming age 59.5."}
    sep_year = (today or date.today()).year + int(max(retire_age - age_on(owner_birth, today), 0))
    if rule_of_55_eligible(owner_birth, sep_year, is_current_employer):
        return {
            "accessible_at": float(d["rule_of_55_age"]),
            "reason": "Rule of 55: leave this employer in or after the year you turn 55 and draw directly from this plan.",
        }
    why = (
        "Not the current employer's plan, so the Rule of 55 does not apply." if not is_current_employer else "Separation would be before the year you turn 55."
    )
    return {"accessible_at": d["normal_age"], "reason": f"{why} Before 59.5 only a 72(t) SEPP or another exception avoids the 10% penalty."}


def rollover_advice(access: dict, is_current_employer: bool) -> dict:
    """Keep / roll recommendation for one pre-tax plan."""
    if access["accessible_at"] <= _data()["rule_of_55_age"]:
        return {
            "action": "keep",
            "reason": "Rolling to an IRA would forfeit the Rule of 55; keep it in the plan until 59.5, or roll only the part beyond your pre-59.5 spending need if the plan allows partial rollovers.",  # noqa: E501
        }
    if is_current_employer:
        return {
            "action": "keep",
            "reason": "Still your current employer's plan: in-service rollovers are usually blocked before 59.5 and the plan keeps ERISA creditor protection.",
        }
    return {
        "action": "consider_roll",
        "reason": "Old-employer plan with no Rule of 55 benefit: roll to an IRA if it lowers fees, widens the fund menu or enables Roth conversions. IRA creditor protection is weaker, and a pre-tax IRA balance breaks backdoor-Roth math.",  # noqa: E501
    }
