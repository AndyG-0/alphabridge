"""Cash-engine extras: Treasury/CD ladder planner, state-tax advantage of T-bills over a money market, emergency + bridge
reserve sizing from the withdrawal simulator, and a DCA schedule. Deterministic, no I/O besides the rule file
(data/cash_rules.json, sources inside). Yields are inputs; nothing here is a market forecast."""

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from services import tax as tax_svc

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "cash_rules.json"


@lru_cache(maxsize=1)
def rules() -> dict:
    return json.loads(DATA_FILE.read_text())


def curve_yield(months: int, tbill_3m: float, ten_year: float) -> float:
    """Linear interpolation by maturity between the 3-month bill and the 10-year note (planning approximation)."""
    m = min(max(months, 3), 120)
    return tbill_3m + (ten_year - tbill_3m) * (m - 3) / (120 - 3)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in range(d.day, 0, -1):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise AssertionError("unreachable")


def build_ladder(amount: float, rungs_months: list[int], yields: dict[int, float], start: date, instrument: str = "TBILL") -> dict:
    """Equal-dollar rungs; each rung's interest is simple for its term (T-bills are discount instruments, close enough here)."""
    if amount <= 0 or not rungs_months:
        return {"instrument": instrument, "amount": max(amount, 0.0), "rungs": [], "blended_yield": 0.0, "annual_interest": 0.0, "next_maturity": None}
    n = len(rungs_months)
    each = round(amount / n, 2)
    amts = [each] * n
    amts[-1] = round(amount - each * (n - 1), 2)  # cents land exactly
    rungs: list[dict] = []
    for months, a in zip(rungs_months, amts, strict=True):
        y = yields[months]
        rungs.append(
            {
                "months": months,
                "amount": a,
                "yield": y,
                "buy_on": start.isoformat(),
                "matures_on": _add_months(start, months).isoformat(),
                "interest_at_maturity": round(a * y * months / 12, 2),
            }
        )
    blended = sum(float(r["amount"]) * float(r["yield"]) for r in rungs) / amount
    return {
        "instrument": instrument,
        "amount": round(amount, 2),
        "rungs": rungs,
        "blended_yield": blended,
        "annual_interest": round(amount * blended, 2),
        "next_maturity": min(str(r["matures_on"]) for r in rungs),
        "roll_note": "When a rung matures, reinvest it at the longest term so the ladder keeps its shape.",
    }


def state_tax_advantage(
    amount: float, mmf_yield: float, tbill_yield: float, state: str | None, federal_rate: float, mmf_treasury_share: float | None = None
) -> dict:
    """After-tax interest on `amount` held in a money market vs. T-bills. Both are federally taxed at `federal_rate`; T-bill
    interest is exempt from state tax, a money market only for its Treasury share."""
    share = rules()["money_market_treasury_share_default"] if mmf_treasury_share is None else min(max(mmf_treasury_share, 0.0), 1.0)
    st = tax_svc.state_rule(state)
    srate = st["flat_rate"]
    mmf_interest = amount * mmf_yield
    tb_interest = amount * tbill_yield
    mmf_after = mmf_interest * (1 - federal_rate - srate * (1 - share))
    tb_after = tb_interest * (1 - federal_rate)
    return {
        "state": st["state"],
        "state_rate": srate,
        "state_rate_known": st["known"],
        "federal_rate": federal_rate,
        "mmf_treasury_share": share,
        "mmf_after_tax": round(mmf_after, 2),
        "tbill_after_tax": round(tb_after, 2),
        "advantage": round(tb_after - mmf_after, 2),
        "mmf_after_tax_yield": mmf_after / amount if amount else 0.0,
        "tbill_after_tax_yield": tb_after / amount if amount else 0.0,
        "winner": "TBILL" if tb_after > mmf_after else "MMF",
        "source_url": rules()["treasury_state_exempt"]["source_url"],
    }


def i_bond_plan(people: int, rate: float | None, tbill_yield: float) -> dict:
    r = rules()["i_bond"]
    cap = r["annual_purchase_limit_per_person"] * max(people, 1)
    out = {
        "annual_purchase_cap": cap,
        "min_hold_months": r["min_hold_months"],
        "early_redemption_penalty": f"{r['penalty_months_of_interest_before_60_months']} months of interest if redeemed before 5 years",
        "source_url": r["source_url"],
        "rate": rate,
    }
    if rate is None:
        out["verdict"] = "Enter the current I-bond composite rate to compare it with T-bills."
    else:
        out["verdict"] = "I-bond rate beats the T-bill yield" if rate > tbill_yield else "T-bills yield more than the I-bond rate and stay liquid"
    return out


def bridge_reserve(rows: list[dict], years: int | None = None) -> dict:
    """Cash for the first N retirement years of withdrawals from a withdrawals.simulate() row list."""
    n = years if years is not None else rules()["reserve"]["sequence_years"]
    used = rows[:n]
    per_year = [r["draw_taxable"] + r["draw_pretax"] + r["draw_roth"] for r in used]
    return {"years": len(used), "per_year": [round(x, 2) for x in per_year], "total": round(sum(per_year), 2), "first_year": used[0]["year"] if used else None}


def emergency_fund(essential_monthly: float, months: float) -> float:
    return round(essential_monthly * months, 2)


def dca_schedule(amount: float, tranches: int, start: date, interval_days: int | None = None) -> list[dict]:
    if amount <= 0 or tranches <= 0:
        return []
    step = interval_days or rules()["dca"]["interval_days"]
    each = round(amount / tranches, 2)
    out = []
    for i in range(tranches):
        a = each if i < tranches - 1 else round(amount - each * (tranches - 1), 2)
        out.append({"on": (start + timedelta(days=step * i)).isoformat(), "amount": a})
    return out


def due_tranches(plan: dict | None, today: date) -> list[dict]:
    """Tranches whose date has arrived and that haven't been reminded yet."""
    if not plan:
        return []
    done = set(plan.get("notified", []))
    return [t for t in plan.get("schedule", []) if t["on"] <= today.isoformat() and t["on"] not in done]
