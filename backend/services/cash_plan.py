"""Glue for the cash page: profile + market -> ladder, T-bill vs money-market tax comparison, reserves and DCA schedule."""

from datetime import date

from models import UserProfile
from services import ladder, tax_lots
from services import liabilities as liab_svc


def build(s, profile: UserProfile, market, mmf_yield: float, p: dict | None = None, today: date | None = None) -> dict:
    """`p` may carry: ladder_amount, rungs (list of months), yields ({months: y}), cd_yield, ibond_rate, mmf_treasury_share."""
    from models import Liability
    from services import ingestion, planner

    p = p or {}
    today = today or date.today()
    rules = ladder.rules()
    debts = s.query(Liability).all()
    essential = liab_svc.essential_monthly(profile, debts)
    cash = ingestion.cash_total(s)
    rec = planner.cash_recommendation(s, profile, mmf_yield, market)

    # Emergency fund stays liquid; what sits in the money market beyond it (and beyond one month of float) can be laddered.
    emergency = ladder.emergency_fund(essential, profile.emergency_fund_target_months)
    float_cash = essential
    available = max(rec["keep_in_mmf"] - emergency - float_cash, 0.0)
    amount = float(p["ladder_amount"]) if p.get("ladder_amount") is not None else available

    rungs = [int(x) for x in (p.get("rungs") or rules["ladder"]["default_rungs_months"])][: rules["ladder"]["max_rungs"]]
    yields = {m: curve_override(p, m, market) for m in rungs}
    inst = "CD" if p.get("cd_yield") is not None else "TBILL"
    if inst == "CD":
        yields = {m: float(p["cd_yield"]) for m in rungs}
    lad = ladder.build_ladder(amount, rungs, yields, today, inst)

    fed = tax_lots._rates(profile, today)["SHORT"]
    tb = yields.get(3, market.tbill_3m) if inst == "TBILL" else market.tbill_3m
    adv = ladder.state_tax_advantage(max(cash, amount), mmf_yield, tb, profile.state, fed, p.get("mmf_treasury_share"))

    people = 2 if profile.spouse_age > 0 else 1
    ib = ladder.i_bond_plan(people, p.get("ibond_rate"), market.tbill_3m)

    # Bridge reserve from the withdrawal simulator (P2): first N years of draws at the target retirement age.
    wd = planner.withdrawal_plan(profile, ("TAXABLE_FIRST",), detail=True)
    rows = wd["strategies"][0].get("years", [])
    reserve = ladder.bridge_reserve(rows)
    reserve["retire_age"] = wd["retire_age"]
    total_target = round(emergency + reserve["total"], 2)

    dca = None
    if rec["deploy_now"] > 0 and rec["tranches"] > 0:
        dca = {"amount": rec["deploy_now"], "tranches": rec["tranches"], "schedule": ladder.dca_schedule(rec["deploy_now"], rec["tranches"], today)}

    return {
        "signal": rec["signal"],
        "ladder": lad,
        "ladder_available": round(available, 2),
        "tax_comparison": adv,
        "i_bond": ib,
        "emergency_fund": {
            "months": profile.emergency_fund_target_months,
            "essential_monthly": essential,
            "target": emergency,
            "have_cash": cash,
            "gap": round(max(emergency - cash, 0.0), 2),
        },
        "bridge_reserve": reserve,
        "total_reserve_target": total_target,
        "dca": dca,
        "notes": [
            rules["ladder"]["curve_note"] if inst == "TBILL" and not p.get("yields") else "Ladder yields are as entered.",
            "Reserve = emergency fund plus the first years of retirement withdrawals; only cash above the emergency fund and one month of float is laddered.",
            "Federal bracket is estimated from your income; state tax uses the flat planning rate in data/state_income_tax.json.",
        ],
    }


def curve_override(p: dict, months: int, market) -> float:
    given = p.get("yields") or {}
    if str(months) in given:
        return float(given[str(months)])
    return ladder.curve_yield(months, market.tbill_3m, market.ten_year)
