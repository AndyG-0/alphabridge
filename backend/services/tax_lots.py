"""Lot-level tax tools: holding periods, wash-sale conflicts, loss-harvest candidates, 0% long-term gain harvesting and specific-lot sales.

All numbers are deterministic. Rules and the "substantially identical" fund groups live in versioned data files with sources. Federal only:
state tax is ignored, and realized gains/losses already booked this year are unknown, so savings are estimates per lot, not a tax return.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from models import Account, Holding, TaxLot, UserProfile
from services import tax

_DATA = Path(__file__).resolve().parent.parent / "data"
TAXABLE = "TAXABLE_BROKERAGE"


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text())


def rules() -> dict:
    return _load("tax_lot_rules.json")


def _groups() -> list[dict]:
    return _load("substantially_identical.json")["groups"]


def identical_group(symbol: str) -> dict:
    """Tickers treated as the same security for wash-sale purposes (just the symbol itself when it isn't in a known group)."""
    sym = symbol.upper()
    for g in _groups():
        if sym in g["tickers"]:
            return {"index": g["index"], "tickers": list(g["tickers"]), "alternatives": [a for a in g["alternatives"] if a not in g["tickers"]]}
    return {"index": None, "tickers": [sym], "alternatives": []}


def term(acquired: date, on: date) -> str:
    return "LONG" if (on - acquired).days > rules()["long_term_days_over"] else "SHORT"


def ordinary_taxable(profile: UserProfile, year: int) -> float:
    income = (profile.annual_income or 0) + ((profile.spouse_annual_income or 0) if profile.tax_filing_status == "MFJ" else 0)
    return max(income - tax.standard_deduction(profile.tax_filing_status, year), 0.0)


def marginal_ordinary_rate(taxable: float, status: str, year: int) -> float:
    return (tax.ordinary_tax(taxable + 1000, status, year)[0] - tax.ordinary_tax(taxable, status, year)[0]) / 1000


def ltcg_rate(taxable: float, status: str, year: int) -> float:
    return tax.ltcg_tax(1000, taxable, status, year) / 1000


def _rates(profile: UserProfile, today: date) -> dict:
    y = tax.rules_year(today.year)
    ot = ordinary_taxable(profile, y)
    return {
        "year": y,
        "ordinary_taxable": ot,
        "SHORT": marginal_ordinary_rate(ot, profile.tax_filing_status, y),
        "LONG": ltcg_rate(ot, profile.tax_filing_status, y),
    }


def lot_view(lot: TaxLot, prices: dict[tuple[int, str], float], today: date) -> dict:
    price = prices.get((lot.account_id, lot.symbol), 0.0)
    value = lot.shares * price if price > 0 else lot.current_value
    return {
        "id": lot.id,
        "account_id": lot.account_id,
        "symbol": lot.symbol,
        "acquired": lot.acquired.isoformat(),
        "shares": lot.shares,
        "cost_basis": lot.cost_basis_total,
        "value": value,
        "gain": value - lot.cost_basis_total,
        "term": term(lot.acquired, today),
        "days_to_long_term": max(rules()["long_term_days_over"] + 1 - (today - lot.acquired).days, 0),
    }


def wash_conflicts(symbol: str, sale_day: date, lots: list[TaxLot], accounts: dict[int, Account], exclude_lot: int | None = None) -> list[dict]:
    """Purchases of the same or a substantially identical fund within 30 days either side of the sale, in ANY account of the household
    (taxable, IRA, Roth, 401(k), spouse's). The lot being sold is excluded."""
    days = rules()["wash_sale_days"]
    ticks = set(identical_group(symbol)["tickers"])
    out = []
    for lot in lots:
        if lot.id == exclude_lot or lot.symbol not in ticks:
            continue
        if abs((lot.acquired - sale_day).days) <= days:
            a = accounts.get(lot.account_id)
            out.append(
                {
                    "lot_id": lot.id,
                    "symbol": lot.symbol,
                    "acquired": lot.acquired.isoformat(),
                    "shares": lot.shares,
                    "account": a.name if a else "",
                    "owner": a.owner if a else "",
                }
            )
    return out


def harvest_candidates(views: list[dict], all_lots: list[TaxLot], accounts: dict[int, Account], profile: UserProfile, today: date) -> dict:
    r, rl = _rates(profile, today), rules()
    cands: list[dict] = []
    blocked: list[dict] = []
    for v in views:
        a = accounts.get(v["account_id"])
        if a is None or a.tax_bucket != TAXABLE or v["gain"] >= -rl["min_harvest_loss"]:
            continue
        loss = -v["gain"]
        rate = r[v["term"]]
        g = identical_group(v["symbol"])
        conflicts = wash_conflicts(v["symbol"], today, all_lots, accounts, exclude_lot=v["id"])
        row = {
            **v,
            "account": a.name,
            "loss": loss,
            "rate": rate,
            "est_tax_savings": loss * rate,
            "identical_to": g["tickers"],
            "alternatives": g["alternatives"],
            "wash_conflicts": conflicts,
            "avoid_buying_until": (today + timedelta(days=rl["wash_sale_days"] + 1)).isoformat(),
        }
        (blocked if conflicts else cands).append(row)
    cands.sort(key=lambda c: -c["est_tax_savings"])
    blocked.sort(key=lambda c: -c["est_tax_savings"])
    return {
        "candidates": cands,
        "blocked_by_wash_sale": blocked,
        "total_loss": sum(c["loss"] for c in cands),
        "total_est_savings": sum(c["est_tax_savings"] for c in cands),
        "ordinary_offset_limit": rl["capital_loss_ordinary_offset"],
        "rates": {"short": r["SHORT"], "long": r["LONG"]},
        "note": (
            "Savings assume the loss offsets gains of the same character first; net losses beyond that offset up to "
            f"${rl['capital_loss_ordinary_offset']:,} of ordinary income per year and carry forward. Federal only. "
            f"Do not buy the same or an identical fund in any household account (IRA, 401(k), spouse) for {rl['wash_sale_days']} days after selling."
        ),
    }


def gain_harvest(views: list[dict], accounts: dict[int, Account], profile: UserProfile, today: date) -> dict:
    """Long-term gains that fit inside the 0% bracket. Headroom = top of the 0% band minus ordinary taxable income; gains already realized
    this year aren't known, so reduce it by whatever you've sold."""
    y = tax.rules_year(today.year)
    status = profile.tax_filing_status
    zero_top = float(tax.table(y)["ltcg"][status]["zero_up_to"])
    headroom = max(zero_top - ordinary_taxable(profile, y), 0.0)
    picks: list[dict] = []
    left = headroom
    pool = [
        v
        for v in views
        if v["term"] == "LONG" and v["gain"] > 0 and (accounts.get(v["account_id"]) is not None) and accounts[v["account_id"]].tax_bucket == TAXABLE
    ]
    for v in sorted(pool, key=lambda v: -(v["gain"] / v["value"] if v["value"] else 0)):
        if left <= 1:
            break
        frac = min(1.0, left / v["gain"])
        gain = v["gain"] * frac
        picks.append(
            {
                "lot_id": v["id"],
                "symbol": v["symbol"],
                "account_id": v["account_id"],
                "shares": v["shares"] * frac,
                "proceeds": v["value"] * frac,
                "gain": gain,
                "new_basis_step_up": gain,
            }
        )
        left -= gain
    return {
        "zero_bracket_top": zero_top,
        "headroom": headroom,
        "picks": picks,
        "total_gain": sum(p["gain"] for p in picks),
        "note": (
            "Realizing gains inside the 0% band and rebuying resets basis higher at no federal tax (wash-sale rules apply to losses only). "
            "Gains can still raise state tax, ACA subsidies or Medicare premiums."
        ),
    }


def suggest_sale(
    views: list[dict],
    symbol: str,
    amount: float,
    profile: UserProfile,
    today: date,
    all_lots: list[TaxLot],
    accounts: dict[int, Account],
    account_id: int | None = None,
) -> dict:
    """Which lots to sell to raise `amount` dollars of `symbol` with the least tax: losses first, then lowest tax per dollar of proceeds."""
    r = _rates(profile, today)
    sym = symbol.upper()
    pool = [v for v in views if v["symbol"] == sym and v["value"] > 0 and (account_id is None or v["account_id"] == account_id)]
    pool = [v for v in pool if (a := accounts.get(v["account_id"])) is not None and a.tax_bucket == TAXABLE]

    def tax_per_dollar(v: dict) -> float:
        return (v["gain"] / v["value"]) * r[v["term"]]

    picks: list[dict] = []
    left = amount
    for v in sorted(pool, key=tax_per_dollar):
        if left <= 0.005:
            break
        proceeds = min(v["value"], left)
        frac = proceeds / v["value"]
        gain = v["gain"] * frac
        picks.append(
            {
                "lot_id": v["id"],
                "account_id": v["account_id"],
                "acquired": v["acquired"],
                "term": v["term"],
                "shares": v["shares"] * frac,
                "proceeds": proceeds,
                "gain": gain,
                "est_tax": gain * r[v["term"]],
            }
        )
        left -= proceeds
    wash = []
    if any(p["gain"] < 0 for p in picks):
        wash = wash_conflicts(sym, today, all_lots, accounts)
    return {
        "symbol": sym,
        "requested": amount,
        "raised": amount - max(left, 0.0),
        "shortfall": max(left, 0.0),
        "picks": picks,
        "total_gain": sum(p["gain"] for p in picks),
        "est_tax": sum(p["est_tax"] for p in picks),
        "wash_conflicts": wash,
        "rates": {"short": r["SHORT"], "long": r["LONG"]},
    }


def report(s, profile: UserProfile, today: date | None = None) -> dict:
    today = today or date.today()
    all_lots = s.query(TaxLot).all()
    accounts = {a.id: a for a in s.query(Account).all()}
    prices = {(h.account_id, h.symbol): h.current_price for h in s.query(Holding).all() if h.current_price}
    views = [lot_view(lot, prices, today) for lot in all_lots]
    covered = {(lot.account_id, lot.symbol) for lot in all_lots}
    missing = sorted(
        {
            h.symbol
            for h in s.query(Holding).all()
            if accounts[h.account_id].tax_bucket == TAXABLE
            and h.market_value > 0
            and h.asset_class != "MONEY_MARKET"
            and (h.account_id, h.symbol) not in covered
        }
    )
    out: dict = {"lots": len(all_lots), "missing_lots": missing}
    if not all_lots:
        out["notes"] = ["Import a lot-level cost-basis export (Fidelity: Positions > Cost basis > Download) to see harvesting and wash-sale checks."]
        return out
    out["harvest"] = harvest_candidates(views, all_lots, accounts, profile, today)
    out["gain_harvest"] = gain_harvest(views, accounts, profile, today)
    out["upcoming_long_term"] = sorted(
        (v for v in views if v["term"] == "SHORT" and v["gain"] > 0 and v["days_to_long_term"] <= 60), key=lambda v: v["days_to_long_term"]
    )[:10]
    out["notes"] = []
    return out
