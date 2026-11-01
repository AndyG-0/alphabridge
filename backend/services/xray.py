"""Portfolio X-Ray (I1): look-through exposure by asset class, sector, geography and market cap; fund overlap; concentration.

Pure math in `build_xray` (no network, no DB); `portfolio_xray` is the DB/market-data wrapper. Fund data that can't be fetched is
reported under `coverage` and its dollars land in "Unclassified" rather than being silently called diversified. Constants live in
data/xray_regions.json and data/xray_fund_fallback.json (source URLs inside)."""

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
UNCLASSIFIED = "Unclassified"
SINGLE_NAME_LIMIT = 0.10


@lru_cache(maxsize=1)
def _regions() -> dict:
    return json.loads((DATA / "xray_regions.json").read_text())


@lru_cache(maxsize=1)
def _fallback() -> dict:
    return json.loads((DATA / "xray_fund_fallback.json").read_text())["funds"]


def region_of(country: str | None) -> str:
    if not country:
        return UNCLASSIFIED
    r = _regions()
    if country == r["home_country"]:
        return "US"
    return "Emerging" if country in r["emerging_countries"] else "Developed ex-US"


def cap_tier(market_cap: float | None) -> str:
    if not market_cap:
        return UNCLASSIFIED
    b = _regions()["market_cap_breakpoints"]
    return "Large" if market_cap >= b["large_min"] else "Mid" if market_cap >= b["mid_min"] else "Small"


def _pretty(sector: str) -> str:
    return sector.replace("_", " ").title()


def _spread(dim: dict[str, float], dollars: float, weights: dict[str, float] | None) -> None:
    """Add `dollars` to `dim` split by `weights` (fractions of the holding); the uncovered remainder is Unclassified."""
    covered = 0.0
    for k, w in (weights or {}).items():
        if w > 0:
            dim[k] = dim.get(k, 0.0) + dollars * w
            covered += w
    rest = max(1.0 - covered, 0.0)
    if rest > 1e-9:
        dim[UNCLASSIFIED] = dim.get(UNCLASSIFIED, 0.0) + dollars * rest


def _fractions(dim: dict[str, float], total: float) -> dict[str, float]:
    if total <= 0:
        return {}
    return dict(sorted(((k, v / total) for k, v in dim.items() if v > 1e-9), key=lambda kv: -kv[1]))


def build_xray(holdings: list[dict], lookthrough: dict[str, dict], fundamentals: dict[str, dict], employer_symbol: str = "") -> dict:
    """holdings: [{symbol, ticker (proxy or symbol), asset_class, value}]. lookthrough: ticker -> live fund data
    ({top_holdings, sectors, asset_mix}). fundamentals: ticker -> {sector, country, market_cap}."""
    asset: dict[str, float] = {}
    sector: dict[str, float] = {}
    region: dict[str, float] = {}
    cap: dict[str, float] = {}
    names: dict[str, float] = {}
    funds: dict[str, dict[str, float]] = {}
    coverage: list[dict] = []
    total = 0.0
    employer = employer_symbol.strip().upper()
    employer_dollars = 0.0

    for h in holdings:
        v = float(h["value"])
        if v <= 0:
            continue
        total += v
        t = h["ticker"].upper()
        ac = h["asset_class"]
        if ac == "MONEY_MARKET":
            _spread(asset, v, {"Cash": 1.0})
            _spread(sector, v, {"Cash": 1.0})
            _spread(region, v, {"US": 1.0})
            continue
        if ac == "INDIVIDUAL_STOCK":
            f = fundamentals.get(t) or {}
            _spread(asset, v, {"Stocks": 1.0})
            _spread(sector, v, {f["sector"]: 1.0} if f.get("sector") else None)
            _spread(region, v, {region_of(f.get("country")): 1.0} if f.get("country") else None)
            _spread(cap, v, {cap_tier(f.get("market_cap")): 1.0} if f.get("market_cap") else None)
            names[t] = names.get(t, 0.0) + v
            if employer and t == employer:
                employer_dollars += v
            if not f:
                coverage.append({"symbol": h["symbol"], "missing": ["sector", "region", "market_cap"]})
            continue
        # fund / ETF / bond fund: live look-through, with the static fallback filling region, cap tier and asset mix
        live = lookthrough.get(t) or {}
        fb = _fallback().get(t, {})
        top = live.get("top_holdings") or {}
        sectors = {_pretty(k): w for k, w in (live.get("sectors") or {}).items()}
        default_mix = {"Bonds": 1.0} if ac == "BOND" else {"Stocks": 1.0}
        mix = live.get("asset_mix") or fb.get("asset_mix") or default_mix
        regions = fb.get("regions") or {}
        caps = fb.get("market_cap") or {}
        _spread(asset, v, mix)
        # sector weights from yfinance cover the equity sleeve only; scale to the fund's stock share
        stock_share = mix.get("Stocks", 0.0)
        sector_w = {k: w * stock_share for k, w in sectors.items()}
        for k in ("Bonds", "Cash"):
            if mix.get(k):
                sector_w[k] = mix[k]
        _spread(sector, v, sector_w)
        _spread(region, v, regions)
        if stock_share:  # market-cap tiers describe the equity sleeve only
            _spread(cap, v * stock_share, caps)
        checks = (("holdings", top), ("sector", sectors or not stock_share), ("region", regions), ("market_cap", caps or not stock_share))
        missing = [d for d, ok in checks if not ok]
        if missing:
            coverage.append({"symbol": h["symbol"], "missing": missing, "fallback_used": bool(fb)})
        if top:
            funds[h["symbol"]] = {n.upper(): w for n, w in top.items()}
            for n, w in top.items():
                names[n.upper()] = names.get(n.upper(), 0.0) + v * w
                if employer and n.upper() == employer:
                    employer_dollars += v * w

    asset_f, sector_f, region_f = _fractions(asset, total), _fractions(sector, total), _fractions(region, total)
    cap_f = _fractions(cap, sum(cap.values()))  # share of equity dollars, not of the whole portfolio
    name_f = _fractions(names, total)
    top_names: list[dict] = [{"symbol": k, "weight": w} for k, w in list(name_f.items())[:10]]
    hhi = sum(w * w for w in name_f.values())
    warnings = [
        f"{n['symbol']} is {n['weight']:.0%} of the portfolio after look-through (limit {SINGLE_NAME_LIMIT:.0%})."
        for n in top_names
        if n["weight"] > SINGLE_NAME_LIMIT and n["symbol"] != employer
    ]
    emp_w = employer_dollars / total if total > 0 else 0.0
    if employer and emp_w > SINGLE_NAME_LIMIT:
        warnings.append(f"Employer stock {employer} is {emp_w:.0%} of the portfolio including fund look-through; your paycheck rides on it too.")
    return {
        "total": total,
        "asset_class": asset_f,
        "sector": sector_f,
        "region": region_f,
        "market_cap": cap_f,
        "overlap": overlap_matrix(funds),
        "concentration": {
            "top_names": top_names,
            "hhi_named": hhi,
            "named_share": sum(name_f.values()),
            "employer_symbol": employer,
            "employer_weight": emp_w,
            "warnings": warnings,
        },
        "coverage": coverage,
        "notes": (
            "Look-through covers each fund's reported top holdings only; other dimensions use live fund data "
            "with an approximate static fallback. Unclassified = no data."
        ),
    }


def overlap_matrix(funds: dict[str, dict[str, float]]) -> list[dict]:
    """Pairwise overlap = sum over shared underlying names of min(weight_a, weight_b), on reported top holdings."""
    syms = sorted(funds)
    out = []
    for i, a in enumerate(syms):
        for b in syms[i + 1 :]:
            shared = set(funds[a]) & set(funds[b])
            out.append({"a": a, "b": b, "overlap": sum(min(funds[a][n], funds[b][n]) for n in shared), "shared": len(shared)})
    return out


def portfolio_xray() -> dict:
    import db
    from models import Account
    from routes._helpers import get_profile
    from services import market_data as md

    holdings = [
        {"symbol": h.symbol, "ticker": h.proxy_ticker or h.symbol, "asset_class": h.asset_class, "value": h.market_value}
        for a in db.session().query(Account).all()
        for h in a.holdings
    ]
    lookthrough: dict[str, dict] = {}
    fundamentals: dict[str, dict] = {}
    for h in holdings:
        t = h["ticker"].upper()
        if h["asset_class"] == "MONEY_MARKET" or t in lookthrough or t in fundamentals:
            continue
        try:
            if h["asset_class"] == "INDIVIDUAL_STOCK":
                fundamentals[t] = md.get_fundamentals(t)
            elif t.replace(".", "").replace("-", "").isalpha():
                lookthrough[t] = md.get_fund_lookthrough(t)
        except Exception:
            pass
    return build_xray(holdings, lookthrough, fundamentals, get_profile().employer_symbol or "")
