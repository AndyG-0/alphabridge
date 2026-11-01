"""Deterministic debt math: amortization, debt-service schedule, essential spend, pay-down-vs-invest. No I/O, no LLM."""

from datetime import date

import numpy as np

HIGH_APR = 0.08  # at or above this, paying down beats any realistic market return
SPLIT_BAND = 0.015  # APR within this of the risk-adjusted equity return -> split the surplus
EQUITY_HAIRCUT = 0.02  # risk haircut on the expected equity return when comparing to a guaranteed APR
HORIZON_MONTHS = 12 * 70  # revolving / never-amortizing debt is treated as ongoing for the whole plan


def amortize(balance: float, apr: float, payment: float) -> dict:
    """Months to payoff and total interest. `months` is None when the payment never retires the balance."""
    if balance <= 0:
        return {"months": 0, "total_interest": 0.0}
    r = apr / 12
    if payment <= 0 or (r > 0 and payment <= balance * r + 1e-9):
        return {"months": None, "total_interest": None}
    if r < 1e-12:  # effectively interest-free; the log formula loses all precision here
        n = int(np.ceil(balance / payment))
        return {"months": n, "total_interest": 0.0}
    n = int(np.ceil(-np.log(1 - balance * r / payment) / np.log1p(r)))
    growth = (1 + r) ** (n - 1)
    final_payment = (balance * growth - payment * (growth - 1) / r) * (1 + r)  # the last payment is partial
    return {"months": n, "total_interest": round(max(payment * (n - 1) + final_payment - balance, 0.0), 2)}


def months_remaining(liab, today: date | None = None) -> int:
    """Months of payments left: the stated payoff date if given, else derived by amortization."""
    today = today or date.today()
    if liab.balance <= 0 or liab.monthly_payment <= 0:
        return 0
    if liab.payoff_date:
        return max((liab.payoff_date.year - today.year) * 12 + liab.payoff_date.month - today.month, 0)
    n = amortize(liab.balance, liab.apr, liab.monthly_payment)["months"]
    return HORIZON_MONTHS if n is None else n


def _extra(liab) -> float:
    return getattr(liab, "extra_monthly_payment", 0.0) or 0.0


def monthly_schedule(liab, months: int, extra_stop_month: int | None = None, today: date | None = None) -> np.ndarray:
    """Nominal payment in each of the next `months` months. Without extra payments this is the fixed
    payment until `months_remaining`; with extra principal the balance is amortized month by month
    (the stated payoff date no longer applies). Extra stops at `extra_stop_month` (e.g. retirement)."""
    out = np.zeros(months)
    extra = _extra(liab)
    if extra <= 0 or liab.balance <= 0 or liab.monthly_payment <= 0:
        n = min(months_remaining(liab, today), months)
        out[:n] = liab.monthly_payment
        return out
    bal, r = liab.balance, liab.apr / 12
    for m in range(months):
        if bal <= 0.005:
            break
        due = bal * (1 + r)
        pay = min(liab.monthly_payment + (extra if extra_stop_month is None or m < extra_stop_month else 0.0), due)
        out[m] = pay
        bal = due - pay
    return out


def extra_payment_effect(liab, extra_stop_month: int | None = None, today: date | None = None) -> dict | None:
    """Months and interest saved by the extra principal, versus the regular payment alone."""
    if _extra(liab) <= 0 or liab.balance <= 0:
        return None
    base = amortize(liab.balance, liab.apr, liab.monthly_payment)
    sched = monthly_schedule(liab, HORIZON_MONTHS, extra_stop_month, today)
    n = int(np.count_nonzero(sched))
    interest = max(float(sched.sum()) - liab.balance, 0.0)
    out = {"months_with_extra": n, "interest_with_extra": round(interest, 2), "months_saved": None, "interest_saved": None}
    if base["months"] is not None:
        out["months_saved"] = max(base["months"] - n, 0)
        out["interest_saved"] = round(max(base["total_interest"] - interest, 0.0), 2)
    today = today or date.today()
    y, m = divmod(today.month - 1 + n, 12)
    out["payoff_date_with_extra"] = date(today.year + y, m + 1, 1).isoformat()
    return out


def debt_service_by_year(liabilities, years: int, today: date | None = None, extra_stop_month: int | None = None) -> np.ndarray:
    """Nominal payments in each of the next `years` years (fixed payments: they do not inflate).
    Extra principal set to stop at RETIREMENT stops at `extra_stop_month`."""
    out = np.zeros(years)
    for liab in liabilities:
        stop = extra_stop_month if getattr(liab, "extra_payment_until", "RETIREMENT") == "RETIREMENT" else None
        sched = monthly_schedule(liab, years * 12, stop, today)
        out += sched.reshape(years, 12).sum(axis=1)
    return out


def escrow_monthly(liabilities) -> float:
    """Property tax / insurance that continue after a mortgage is paid off (today's dollars)."""
    return sum(liab.escrow_monthly for liab in liabilities)


def current_debt_service_monthly(liabilities, today: date | None = None) -> float:
    """Monthly P&I still being paid plus escrow, which never stops."""
    return sum(liab.monthly_payment for liab in liabilities if months_remaining(liab, today) > 0) + escrow_monthly(liabilities)


def essential_monthly(profile, liabilities, today: date | None = None) -> float:
    """What must be paid even in a downturn: living costs plus debt service. Profile expense fields are
    living costs *excluding* debt payments; the liabilities supply those."""
    return profile.monthly_expenses_current + current_debt_service_monthly(liabilities, today)


def total_balance(liabilities) -> float:
    return sum(liab.balance for liab in liabilities)


def paydown_vs_invest(liab, mmf_yield: float, expected_equity_return: float, tax_rate: float = 0.0) -> dict:
    """Guaranteed return from retiring a debt (its APR) vs. cash yield and risk-adjusted equity return."""
    risk_adj = expected_equity_return * (1 - 0.5 * tax_rate) - EQUITY_HAIRCUT
    if liab.balance <= 0:
        action, frac, why = "NONE", 0.0, "No balance."
    elif liab.apr >= HIGH_APR:
        action, frac = "PAY_DOWN", 1.0
        why = f"{liab.apr:.1%} APR is a guaranteed return no market allocation reliably beats; clear it before investing."
    elif liab.apr <= mmf_yield:
        action, frac = "INVEST", 0.0
        why = f"{liab.apr:.1%} APR is below the {mmf_yield:.1%} cash yield; keep the loan and the cash."
    elif liab.apr > risk_adj:
        action, frac = "PAY_DOWN", 1.0
        why = f"{liab.apr:.1%} APR exceeds the {risk_adj:.1%} risk-adjusted expected equity return."
    elif liab.apr >= risk_adj - SPLIT_BAND:
        action, frac = "SPLIT", 0.5
        why = f"{liab.apr:.1%} APR is close to the {risk_adj:.1%} risk-adjusted equity return; split extra cash 50/50."
    else:
        action, frac = "INVEST", 0.0
        why = f"{liab.apr:.1%} APR is well below the {risk_adj:.1%} risk-adjusted equity return."
    return {
        "id": liab.id,
        "name": liab.name,
        "kind": liab.kind,
        "balance": liab.balance,
        "apr": liab.apr,
        "action": action,
        "pay_down_amount": round(liab.balance * frac, 2),
        "reason": why,
    }


def debt_summary(profile, liabilities, mmf_yield: float, expected_equity_return: float, today: date | None = None) -> dict:
    """Everything the Command Center / LLM needs about debt, as structured JSON."""
    items = []
    retire_m = max(round((profile.target_retirement_age - profile.current_age) * 12), 0)
    for liab in liabilities:
        n = months_remaining(liab, today)
        am = amortize(liab.balance, liab.apr, liab.monthly_payment)
        stop = retire_m if getattr(liab, "extra_payment_until", "RETIREMENT") == "RETIREMENT" else None
        items.append(
            {
                **liab.to_dict(),
                "months_remaining": n if n < HORIZON_MONTHS else None,
                "total_interest_remaining": am["total_interest"],
                "extra_payment": extra_payment_effect(liab, stop, today),
                "recommendation": paydown_vs_invest(liab, mmf_yield, expected_equity_return, profile.effective_tax_rate),
            }
        )
    monthly_income = profile.annual_income / 12
    return {
        "total_balance": total_balance(liabilities),
        "monthly_debt_service": round(sum(liab.monthly_payment for liab in liabilities), 2),
        "monthly_escrow": round(escrow_monthly(liabilities), 2),
        "debt_to_income": round(sum(liab.monthly_payment for liab in liabilities) / monthly_income, 4) if monthly_income > 0 else None,
        "liabilities": items,
    }
