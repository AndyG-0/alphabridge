"""How the portfolio actually did: time- and money-weighted returns, benchmark comparisons, fee drag and an income calendar.

Pure functions take plain values (dates, floats); `report()` wires them to the DB and cached market data. No LLM, no arithmetic elsewhere.
"""

import json
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path

from scipy.optimize import brentq

from models import AllowedPlanMenu, CashFlow, Holding
from services import assumptions, networth

_DATA = Path(__file__).resolve().parent.parent / "data"
MONEY_MARKET = "MONEY_MARKET"


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text())


def twr(points: list[tuple[date, float]], flows: list[tuple[date, float]]) -> dict:
    """Time-weighted return by chaining sub-period returns between snapshots. A flow dated inside (d0, d1] is treated as arriving at the
    end of the period, so r = (V1 - flow) / V0 - 1. points are (date, portfolio value), oldest first; flows are +deposit / -withdrawal."""
    pts = sorted(points)
    growth = 1.0
    periods: list[dict] = []
    for (d0, v0), (d1, v1) in pairwise(pts):
        if v0 <= 0:
            continue  # nothing invested to earn a return yet
        f = sum(a for d, a in flows if d0 < d <= d1)
        r = (v1 - f) / v0 - 1
        growth *= 1 + r
        periods.append({"start": d0.isoformat(), "end": d1.isoformat(), "return": r})
    days = (pts[-1][0] - pts[0][0]).days if len(pts) >= 2 else 0
    total = growth - 1 if periods else None
    return {"total": total, "annualized": annualize(total, days), "days": days, "periods": periods}


def annualize(total: float | None, days: int) -> float | None:
    """Annualized only for windows of at least a year; shorter ones would extrapolate noise."""
    if total is None or days < 365:
        return None
    return (1 + total) ** (365 / days) - 1


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annual rate r with sum(amount / (1+r)^(days/365)) = 0. None when the flows have no sign change or no root in (-99%, +1000%)."""
    if len(flows) < 2 or not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = min(d for d, _ in flows)

    def npv(r: float) -> float:
        return sum(a / (1 + r) ** ((d - t0).days / 365) for d, a in flows)

    try:
        return float(brentq(npv, -0.99, 10.0))
    except ValueError:
        return None


def mwr(points: list[tuple[date, float]], flows: list[tuple[date, float]]) -> float | None:
    """Money-weighted (IRR): start value and deposits are outflows from you, withdrawals and the ending value are inflows."""
    pts = sorted(points)
    if len(pts) < 2 or pts[0][1] <= 0:
        return None
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    cf = [(d0, -v0), (d1, v1)] + [(d, -a) for d, a in flows if d0 < d <= d1]
    return xirr(cf)


def window_return(closes: list[float], start: date, end: date, today: date, trading_days: int = 252) -> float | None:
    """Return of a price series between two past dates, with the series assumed to end today and dates mapped to trading days."""
    n_end = round((today - end).days * trading_days / 365)
    n_start = round((today - start).days * trading_days / 365)
    if n_start <= n_end or n_start >= len(closes):
        return None
    last, first = closes[len(closes) - 1 - n_end], closes[len(closes) - 1 - n_start]
    return last / first - 1 if first > 0 else None


def blend(weights: dict[str, float], returns: dict[str, float | None]) -> float | None:
    """Static-weight blend of per-class returns (rebalanced at the start only); None if any weighted class has no return."""
    tot = sum(weights.values())
    if tot <= 0 or any(w > 0 and returns.get(k) is None for k, w in weights.items()):
        return None
    return sum(w / tot * (returns[k] or 0.0) for k, w in weights.items())


def holding_fees(holdings: list[Holding], menu: dict[tuple[int, str], float], table: dict[str, float]) -> dict:
    """Annual fee dollars from known expense ratios (plan menu first, then the fee table); single stocks and cash-like cash cost nothing here."""
    rows: list[dict] = []
    unknown: list[str] = []
    covered = 0.0
    total = sum(h.market_value for h in holdings)
    for h in holdings:
        if h.market_value <= 0:
            continue
        er = menu.get((h.account_id, h.symbol))
        if er is None:
            er = table.get(h.symbol)
        if er is None and h.asset_class == "INDIVIDUAL_STOCK":
            er = 0.0
        if er is None:
            unknown.append(h.symbol)
            continue
        covered += h.market_value
        rows.append({"symbol": h.symbol, "value": h.market_value, "expense_ratio": er, "annual_fee": h.market_value * er})
    fee = sum(r["annual_fee"] for r in rows)
    return {
        "annual_fee": fee,
        "weighted_expense_ratio": fee / covered if covered else 0.0,
        "covered_pct": covered / total if total else 0.0,
        "unknown": sorted(set(unknown)),
        "rows": sorted(rows, key=lambda r: -r["annual_fee"])[:15],
    }


QUARTERLY_MONTHS = (3, 6, 9, 12)


def income_calendar(holdings: list[Holding], yields: dict[str, float], mmf_yield: float) -> dict:
    """Expected dividend/interest by month: money markets pay monthly, everything else is assumed quarterly (Mar/Jun/Sep/Dec) because
    the data source gives yield but not pay dates. Yield is trailing, so this is an estimate, not a forecast."""
    months = [0.0] * 12
    by_holding: list[dict] = []
    missing: list[str] = []
    for h in holdings:
        if h.market_value <= 0:
            continue
        y = mmf_yield if h.asset_class == MONEY_MARKET else yields.get(h.symbol)
        if y is None:
            if h.asset_class != "INDIVIDUAL_STOCK":
                missing.append(h.symbol)
            continue
        annual = h.market_value * y
        if annual <= 0:
            continue
        by_holding.append({"symbol": h.symbol, "annual_income": annual, "yield": y})
        if h.asset_class == MONEY_MARKET:
            for i in range(12):
                months[i] += annual / 12
        else:
            for m in QUARTERLY_MONTHS:
                months[m - 1] += annual / 4
    total = sum(months)
    return {
        "months": [{"month": i + 1, "amount": a} for i, a in enumerate(months)],
        "annual_income": total,
        "by_holding": sorted(by_holding, key=lambda r: -r["annual_income"])[:15],
        "missing_yield": sorted(set(missing)),
        "assumption": "Money markets pay monthly; other holdings are assumed quarterly (Mar/Jun/Sep/Dec) on trailing yield.",
    }


def normalize_yield(v: float | None) -> float | None:
    """yfinance has returned dividendYield as both a fraction (0.0123) and a percent (1.23); nothing real yields over 25%."""
    if v is None:
        return None
    return v / 100 if v > 0.25 else v


def month_end_flows(start: date, end: date, amount: float) -> list[tuple[date, float]]:
    """Assumed deposits: `amount` on the last day of each month strictly after start, through end (estimate when no flows are recorded)."""
    out: list[tuple[date, float]] = []
    y, m = start.year, start.month
    while True:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        eom = date.fromordinal(nxt.toordinal() - 1)
        if eom > end:
            return out
        out.append((eom, amount))


def invested_points(series: list[dict]) -> list[tuple[date, float]]:
    """Invested assets per snapshot day (debts excluded); the last snapshot of a day wins."""
    by_day: dict[date, float] = {}
    for r in series:
        by_day[datetime.fromisoformat(r["taken_at"]).date()] = r["safe_core"] + r["satellite"] + r["dry_powder"]
    return sorted(by_day.items())


def report(s, profile, closes_fn, fundamentals_fn, today: date | None = None, assume_contributions: bool = False) -> dict:
    today = today or date.today()
    bench = _load("benchmarks.json")
    series = networth.history(s)
    points = invested_points(series)
    holdings = s.query(Holding).all()
    flows = [(f.on, f.amount) for f in s.query(CashFlow).order_by(CashFlow.on)]
    flow_mode = "recorded" if flows else "none"
    if not flows and assume_contributions and len(points) >= 2 and profile.monthly_contribution:
        flows, flow_mode = month_end_flows(points[0][0], points[-1][0], profile.monthly_contribution), "assumed_monthly_contribution"

    out: dict = {"points": len(points), "flow_mode": flow_mode, "flows": len(flows)}
    notes = []
    if len(points) < 2:
        out["returns"] = None
        notes.append("Performance needs at least two net-worth snapshots on different days; history builds from daily snapshots and imports.")
    else:
        t, m = twr(points, flows), mwr(points, flows)
        out["returns"] = {
            "twr": t,
            "mwr": m,
            "start": points[0][0].isoformat(),
            "end": points[-1][0].isoformat(),
            "start_value": points[0][1],
            "end_value": points[-1][1],
        }
        if flow_mode == "none":
            notes.append("No deposits/withdrawals recorded, so returns include anything you added. Record cash flows or assume your monthly contribution.")
        out["benchmarks"] = _benchmarks(profile, points, t["total"], closes_fn, bench, today)
    out["notes"] = notes
    out["fees"] = _fees(s, profile, holdings, bench)
    yields = {}
    for h in holdings:
        if h.asset_class != MONEY_MARKET and h.market_value > 0 and h.symbol not in yields:
            try:
                f = fundamentals_fn(h.symbol)
            except Exception:
                continue
            y = normalize_yield(f.get("dividend_yield"))
            if y is not None:
                yields[h.symbol] = y
    out["income"] = income_calendar(holdings, yields, profile.current_money_market_yield)
    return out


def _benchmarks(profile, points, port_twr, closes_fn, bench, today) -> dict:
    start, end = points[0][0], points[-1][0]
    td = bench["trading_days_per_year"]
    cache: dict[str, float | None] = {}

    def px(sym: str) -> float | None:
        if sym not in cache:
            try:
                cache[sym] = window_return(closes_fn(sym), start, end, today, td)
            except Exception:
                cache[sym] = None
        return cache[sym]

    years = (end - start).days / 365
    class_ret: dict[str, float | None] = {}
    for cls, sym in bench["class_proxies"].items():
        class_ret[cls] = (1 + profile.current_money_market_yield) ** years - 1 if sym is None else px(sym)

    def comp(label: str, ret: float | None) -> dict:
        return {"name": label, "return": ret, "excess": (port_twr - ret) if (port_twr is not None and ret is not None) else None}

    out = {"market": comp(f"{bench['market']} (US stocks)", px(bench["market"])), "target": None, "mix": None, "approximate": True}
    if profile.target_allocation:
        out["target"] = comp("Your target allocation", blend(profile.target_allocation, class_ret))
    return out | {"class_returns": class_ret}


def _fees(s, profile, holdings, bench) -> dict:
    menu = {(m.account_id, m.ticker_or_cusip): m.expense_ratio for m in s.query(AllowedPlanMenu).all() if m.expense_ratio is not None}
    res = holding_fees(holdings, menu, _load("fund_fees.json")["expense_ratios"])
    total = sum(h.market_value for h in holdings)
    if total > 0 and res["weighted_expense_ratio"] > 0:
        gross = networth.plan_return(s)
        res["drag"] = {y: assumptions.fee_drag(total, (profile.monthly_contribution or 0) * 12, y, gross, res["weighted_expense_ratio"]) for y in (10, 20, 30)}
    else:
        res["drag"] = {}
    return res
