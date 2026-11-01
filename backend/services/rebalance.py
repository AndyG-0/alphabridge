"""Drift against the target allocation, a self-funding trade list that respects 401(k) menus and taxes, and asset-location hints.

Every trade sells an overweight class and buys an underweight one inside the same account, so no money has to move between accounts
(a 401(k) can't send cash to a brokerage). Taxable accounts sell the lowest-gain holdings first and their realized gains are priced with
`tax.ltcg_tax`. Holdings carry an average cost, so gains are treated as long-term until lot-level tracking (I4) exists.
"""

import json
from datetime import date
from pathlib import Path

from models import Account, AllowedPlanMenu, Holding
from services import tax

_DATA = Path(__file__).resolve().parent.parent / "data"
MONEY_MARKET = "MONEY_MARKET"
TAXABLE = "TAXABLE_BROKERAGE"
DEFAULT_THRESHOLD = 0.05  # absolute percentage points of the portfolio
MIN_TRADE = 1.0  # dollars; below this nothing is worth a ticket
_ORDER = {"PRE_TAX_401K": 0, "ROTH": 0, "HSA": 0, "CASH_MMF": 1, TAXABLE: 2}  # tax-advantaged first


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text())


def class_values(holdings: list[Holding]) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in holdings:
        if h.market_value > 0:
            out[h.asset_class] = out.get(h.asset_class, 0.0) + h.market_value
    return out


def drift(values: dict[str, float], target: dict[str, float], threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Per-class current vs target weight. `breach` marks classes beyond the threshold; `total_drift` is half the sum of absolute drifts
    (the share of the portfolio that must move)."""
    total = sum(values.values())
    tsum = sum(target.values())
    rows: list[dict] = []
    for k in sorted(set(values) | {k for k, w in target.items() if w > 0}):
        cur = values.get(k, 0.0) / total if total else 0.0
        tgt = target.get(k, 0.0) / tsum if tsum else 0.0
        rows.append({"asset_class": k, "current": cur, "target": tgt, "drift": cur - tgt, "dollars": (tgt - cur) * total, "breach": abs(cur - tgt) > threshold})
    return {
        "total": total,
        "rows": rows,
        "total_drift": sum(abs(r["drift"]) for r in rows) / 2,
        "threshold": threshold,
        "breached": any(r["breach"] for r in rows),
    }


def _buy_symbol(acct: Account, cls: str, menu: list[AllowedPlanMenu], proxies: dict[str, str | None]) -> tuple[str, str] | None:
    """(symbol, name) this account can buy for an asset class, or None. Plan accounts are limited to their menu (cheapest first)."""
    if acct.is_restricted_plan:
        opts = sorted((m for m in menu if m.asset_class == cls), key=lambda m: m.expense_ratio if m.expense_ratio is not None else 9.9)
        return (opts[0].ticker_or_cusip, opts[0].fund_name) if opts else None
    held = [h for h in acct.holdings if h.asset_class == cls and h.market_value > 0]
    if held:
        best = max(held, key=lambda h: h.market_value)
        return best.symbol, best.name or best.symbol
    sym = "SPAXX" if cls == MONEY_MARKET else proxies.get(cls)
    return (sym, sym) if sym else None


def _gain_ratio(h: Holding) -> float:
    """Unrealized gain per dollar sold; unknown basis counts as all gain, the conservative case."""
    if h.market_value <= 0:
        return 0.0
    if not h.cost_basis_total:
        return 1.0
    return (h.market_value - h.cost_basis_total) / h.market_value


def plan_trades(accounts: list[Account], menus: dict[int, list[AllowedPlanMenu]], deltas: dict[str, float], proxies: dict[str, str | None]) -> dict:
    """Greedy, self-funding trades. `deltas` is dollars to add (+) or remove (-) per asset class and sums to ~0."""
    need_sell = {k: -v for k, v in deltas.items() if v < -MIN_TRADE}
    need_buy = {k: v for k, v in deltas.items() if v > MIN_TRADE}
    trades: list[dict] = []
    for acct in sorted(accounts, key=lambda a: (_ORDER.get(a.tax_bucket, 1), a.id)):
        sellable: dict[int, float] = {h.id: h.market_value for h in acct.holdings if h.market_value > 0}
        taxable = acct.tax_bucket == TAXABLE
        while True:
            buy_opts: dict[str, tuple[str, str]] = {}
            for k, v in need_buy.items():
                opt = _buy_symbol(acct, k, menus.get(acct.id, []), proxies) if v > MIN_TRADE else None
                if opt:
                    buy_opts[k] = opt
            if not buy_opts:
                break
            cands = [h for h in acct.holdings if need_sell.get(h.asset_class, 0) > MIN_TRADE and sellable.get(h.id, 0) > MIN_TRADE]
            if not cands:
                break
            h = min(cands, key=_gain_ratio) if taxable else max(cands, key=lambda x: sellable[x.id])
            # buy the class with the biggest remaining need that this account can hold
            bcls = max(buy_opts, key=lambda k: need_buy[k])
            if bcls == h.asset_class:
                break
            amt = min(sellable[h.id], need_sell[h.asset_class], need_buy[bcls])
            if amt <= MIN_TRADE:
                break
            gain = amt * _gain_ratio(h) if taxable else 0.0
            sym, nm = buy_opts[bcls]
            trades.append(
                {
                    "account_id": acct.id,
                    "account": acct.name,
                    "tax_bucket": acct.tax_bucket,
                    "action": "SELL",
                    "symbol": h.symbol,
                    "asset_class": h.asset_class,
                    "amount": amt,
                    "realized_gain": gain,
                }
            )
            trades.append(
                {
                    "account_id": acct.id,
                    "account": acct.name,
                    "tax_bucket": acct.tax_bucket,
                    "action": "BUY",
                    "symbol": sym,
                    "name": nm,
                    "asset_class": bcls,
                    "amount": amt,
                    "realized_gain": 0.0,
                }
            )
            sellable[h.id] -= amt
            need_sell[h.asset_class] -= amt
            need_buy[bcls] -= amt
    unresolved = {
        "sell": {k: v for k, v in need_sell.items() if v > MIN_TRADE},
        "buy": {k: v for k, v in need_buy.items() if v > MIN_TRADE},
    }
    return {"trades": trades, "unresolved": unresolved}


def _year() -> int:
    return tax.rules_year(date.today().year)


def tax_cost(gains: float, profile) -> float:
    """Federal tax on realized gains stacked on top of ordinary income (long-term rates)."""
    if gains <= 0:
        return 0.0
    y = _year()
    status = profile.tax_filing_status
    ordinary_taxable = max((profile.annual_income or 0) - tax.standard_deduction(status, y), 0.0)
    return tax.ltcg_tax(gains, ordinary_taxable, status, y)


def post_trade_values(values: dict[str, float], trades: list[dict]) -> dict[str, float]:
    out = dict(values)
    for t in trades:
        out[t["asset_class"]] = out.get(t["asset_class"], 0.0) + (t["amount"] if t["action"] == "BUY" else -t["amount"])
    return out


def asset_location(accounts: list[Account], profile) -> dict:
    """Where each asset class should live. Flags holdings sitting in a worse bucket than one with room for them, with a rough annual tax-drag
    estimate (value x assumed yield x marginal-rate gap) so the suggestions can be ranked."""
    cfg = _load("asset_location.json")
    pref, yields, ordinary = cfg["preferred"], cfg["taxable_yield_assumption"], set(cfg["ordinary_income_classes"])
    bucket_value: dict[str, float] = {}
    for a in accounts:
        bucket_value[a.tax_bucket] = bucket_value.get(a.tax_bucket, 0.0) + sum(h.market_value for h in a.holdings)
    y = _year()
    status = profile.tax_filing_status
    ordinary_taxable = max((profile.annual_income or 0) - tax.standard_deduction(status, y), 0.0)
    marginal = tax.ordinary_tax(ordinary_taxable + 1000, status, y)[0] - tax.ordinary_tax(ordinary_taxable, status, y)[0]
    marginal /= 1000
    suggestions = []
    for a in accounts:
        if a.tax_bucket == "CASH_MMF":
            continue
        for h in a.holdings:
            order = pref.get(h.asset_class)
            if not order or h.market_value <= 0 or a.tax_bucket not in order:
                continue
            better = [b for b in order[: order.index(a.tax_bucket)] if bucket_value.get(b, 0) > 0]
            if not better:
                continue
            drag = 0.0
            if a.tax_bucket == TAXABLE and h.asset_class in ordinary:
                drag = h.market_value * yields.get(h.asset_class, 0.0) * marginal
            suggestions.append(
                {
                    "symbol": h.symbol,
                    "asset_class": h.asset_class,
                    "account": a.name,
                    "from_bucket": a.tax_bucket,
                    "to_bucket": better[0],
                    "value": h.market_value,
                    "est_annual_tax_drag": drag,
                    "why": "Interest is taxed as ordinary income; tax-deferred space shelters it."
                    if h.asset_class in ordinary
                    else "Preferred placement for this asset class.",
                }
            )
    suggestions.sort(key=lambda r: (-r["est_annual_tax_drag"], -r["value"]))
    return {
        "marginal_rate": marginal,
        "suggestions": suggestions[:15],
        "bucket_value": bucket_value,
        "note": (
            "Moving holdings between account types needs new contributions or in-account swaps; selling in a taxable account realizes gains. "
            "Treat these as placement goals for new money."
        ),
    }


def report(s, profile, threshold: float = DEFAULT_THRESHOLD) -> dict:
    accounts = s.query(Account).all()
    holdings = [h for a in accounts for h in a.holdings]
    target = profile.target_allocation or {}
    base: dict = {"has_target": bool(target)}
    if not target:
        base["notes"] = ["Set a target allocation (asset class weights summing to 100%) in your profile to see drift and trades."]
        base["asset_location"] = asset_location(accounts, profile)
        return base
    values = class_values(holdings)
    d = drift(values, target, threshold)
    deltas = {r["asset_class"]: r["dollars"] for r in d["rows"]}
    menus: dict[int, list[AllowedPlanMenu]] = {}
    for m in s.query(AllowedPlanMenu).all():
        menus.setdefault(m.account_id, []).append(m)
    proxies = _load("benchmarks.json")["class_proxies"]
    plan = plan_trades(accounts, menus, deltas, proxies)
    gains = sum(t["realized_gain"] for t in plan["trades"])
    after = drift(post_trade_values(values, plan["trades"]), target, threshold)
    return base | {
        "drift": d,
        "trades": plan["trades"],
        "unresolved": plan["unresolved"],
        "realized_gains": gains,
        "est_tax": tax_cost(gains, profile),
        "after": {"total_drift": after["total_drift"], "rows": after["rows"]},
        "asset_location": asset_location(accounts, profile),
        "notes": ["Gains use average cost and assume long-term; lot-level tracking refines this."],
    }
