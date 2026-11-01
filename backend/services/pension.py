"""Cash-balance pension math. Pure functions, no I/O, no LLM.

Everything is in today's dollars: interest credits are converted to a real rate and pay stays flat in real terms,
which matches the planner's convention for planned events."""

import math
from datetime import date

from services import household
from services.quant_engine import INFLATION

# Level annuity is paid out to this age at a real discount rate below the plan's crediting rate. The statement
# does not print the plan's annuity conversion factors, so this is a deliberately conservative assumption.
ANNUITY_END_AGE = 95
ANNUITY_REAL_RATE = 0.01


def real_rate(nominal: float, inflation: float = INFLATION) -> float:
    return (1 + nominal) / (1 + inflation) - 1


def project_balance(balance: float, nominal_rate: float, annual_credit: float, years_working: float, years_to_start: float) -> float:
    """Real balance when benefits start: grows at the real crediting rate, plus a flat real pay credit each year
    the owner is still working, then interest only until `years_to_start`."""
    r = real_rate(nominal_rate)
    work = min(max(math.ceil(years_working - 1e-9), 0), max(math.ceil(years_to_start - 1e-9), 0))
    wait = max(years_to_start - work, 0)
    b = balance
    for _ in range(work):
        b = b * (1 + r) + annual_credit
    return b * (1 + r) ** wait


def monthly_annuity(balance: float, start_age: float, end_age: float = ANNUITY_END_AGE, rate: float = ANNUITY_REAL_RATE) -> float:
    n = max(round((end_age - start_age) * 12), 1)
    i = rate / 12
    return balance / n if i == 0 else balance * i / (1 - (1 + i) ** -n)


def projection(p, owner_age_now: float, owner_retire_age: float) -> dict:
    """Projected benefit for one Pension row given the owner's current age and (what-if) retirement age."""
    to_start = max(p.start_age - owner_age_now, 0)
    working = max(owner_retire_age - owner_age_now, 0)
    credit = p.pay_credit_pct * p.covered_pay_annual
    bal = project_balance(p.plan_balance, p.interest_credit_rate, credit, working, to_start)
    return {
        "balance_at_start": round(bal, 2),
        "monthly": round(monthly_annuity(bal, p.start_age), 2) if p.payout == "ANNUITY" else 0.0,
        "years_to_start": round(to_start, 2),
        "years_of_credits": round(min(working, to_start), 2),
    }


def virtual_events(pensions, profile, retire_age: float | None = None, today: date | None = None) -> list:
    """Planner events (never persisted) for each pension, so retirement-age what-ifs change the benefit."""
    from models import PlannedEvent

    year = (today or date.today()).year
    out = []
    by_key = {p.key: p for p in household.people(profile, retire_age)}
    for pen in pensions:
        person = by_key.get(pen.owner)
        if person is None or pen.plan_balance <= 0:
            continue
        proj = projection(pen, person.age_now, person.retire_age)
        start_year = year + household.year_index(proj["years_to_start"])
        lump = pen.payout == "LUMP_SUM"
        amount = proj["balance_at_start"] if lump else proj["monthly"]
        if amount <= 0:
            continue
        out.append(
            PlannedEvent(
                name=f"{pen.name} ({'lump sum' if lump else 'annuity'})",
                kind="INFLOW" if lump else "PENSION",
                amount=amount,
                start_year=start_year,
                repeat_every_years=0,
                repeat_until_year=None,
                owner=pen.owner,
                financed=False,
                down_payment=0.0,
                loan_apr=0.0,
                loan_term_months=60,
                is_home_sale=False,
            )
        )
    return out
