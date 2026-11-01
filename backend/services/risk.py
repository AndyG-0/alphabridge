"""Risk analytics for the actual portfolio: volatility, drawdown, historical VaR/CVaR, beta, correlations, risk contribution and stress tests.

Everything is computed from cached daily closes (current weights held constant over the window) and from the annual history in
`data/historical_returns.json`. Pure functions take arrays; `report()` wires them to holdings and market data. No LLM involved.
"""

import json
from pathlib import Path

import numpy as np

from models import Holding
from services import quant_engine as qe

_DATA = Path(__file__).resolve().parent.parent / "data"
MONEY_MARKET = "MONEY_MARKET"


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text())


def daily_returns(closes: list[float]) -> np.ndarray:
    c = np.asarray(closes, float)
    return c[1:] / c[:-1] - 1 if len(c) >= 2 else np.array([])


def portfolio_returns(series: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """Weighted sum of aligned (most-recent-n) daily return series with constant weights; weights are renormalized over symbols present."""
    keys = [k for k in weights if k in series and len(series[k]) > 1 and weights[k] > 0]
    if not keys:
        return np.array([])
    n = min(len(series[k]) for k in keys)
    tot = sum(weights[k] for k in keys)
    out = np.zeros(n)
    for k in keys:
        out += weights[k] / tot * np.asarray(series[k])[-n:]
    return out


def stats(returns: np.ndarray, value: float, confidence: float = 0.95, periods: int = 252) -> dict:
    """Annualized volatility, max drawdown of the compounded path, and 1-day historical VaR/CVaR (as positive loss fractions and dollars)."""
    r = np.asarray(returns, float)
    if len(r) < 20:
        return {}
    path = np.cumprod(1 + r)
    cut = np.percentile(r, (1 - confidence) * 100)
    tail = r[r <= cut]
    var, cvar = max(-float(cut), 0.0), max(-float(tail.mean()), 0.0)
    return {
        "days": len(r),
        "volatility": float(r.std(ddof=1) * np.sqrt(periods)),
        "max_drawdown": float((path / np.maximum.accumulate(path) - 1).min()),
        "var_1d": var,
        "cvar_1d": cvar,
        "var_1d_dollars": var * value,
        "cvar_1d_dollars": cvar * value,
        "confidence": confidence,
    }


def risk_contribution(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Share of portfolio variance from each position: w_i (Σw)_i / wᵀΣw. Sums to 1 and can be negative for a hedge."""
    w = np.asarray(weights, float)
    marginal = cov @ w
    var = float(w @ marginal)
    return w * marginal / var if var > 0 else np.zeros_like(w)


def scenario_return(scn: dict, years: dict, series: str) -> float:
    g = 1.0
    for y in scn["years"]:
        g *= 1 + years[str(y)][series]
    return g - 1


def stress(values: dict[str, float], betas: dict[str, float] | None = None) -> list[dict]:
    """Apply each historical scenario to dollars held per asset class. Equity classes take the S&P total return times a sensitivity
    (>1 for sectors and single stocks); bonds use the 10-year Treasury series and money markets the T-bill series."""
    cfg, years = _load("risk_scenarios.json"), _load("historical_returns.json")["years"]
    total = sum(values.values())
    out = []
    for scn in cfg["scenarios"]:
        by_class, loss = {}, 0.0
        for cls, v in values.items():
            series = cfg["class_series"].get(cls, "stocks")
            ret = scenario_return(scn, years, series)
            if series == "stocks":
                sens = (betas or {}).get(cls, cfg["equity_sensitivity"].get(cls, 1.0))
                ret = max(ret * sens, -1.0)
            by_class[cls] = {"return": ret, "change": v * ret}
            loss += v * ret
        out.append(
            {
                "id": scn["id"],
                "label": scn["label"],
                "years": scn["years"],
                "portfolio_change": loss,
                "portfolio_return": loss / total if total else 0.0,
                "by_class": by_class,
                "benchmark": {s: scenario_return(scn, years, s) for s in ("stocks", "bonds", "bills")},
            }
        )
    return out


def report(s, closes_fn, market_symbol: str = "SPY") -> dict:
    cfg, bench = _load("risk_scenarios.json"), _load("benchmarks.json")
    holdings = s.query(Holding).all()
    total = sum(h.market_value for h in holdings if h.market_value > 0)
    class_values: dict[str, float] = {}
    for h in holdings:
        if h.market_value > 0:
            class_values[h.asset_class] = class_values.get(h.asset_class, 0.0) + h.market_value
    out: dict = {"total": total, "stress": stress(class_values), "notes": []}
    if total <= 0:
        out["notes"].append("No holdings yet.")
        return out

    by_symbol: dict[str, float] = {}
    sym_class: dict[str, str] = {}
    proxy_for: dict[str, str] = {}
    for h in holdings:
        if h.market_value <= 0 or h.asset_class == MONEY_MARKET:
            continue
        by_symbol[h.symbol] = by_symbol.get(h.symbol, 0.0) + h.market_value
        sym_class[h.symbol] = h.asset_class
        proxy_for.setdefault(h.symbol, h.proxy_ticker or h.symbol)
    cash = class_values.get(MONEY_MARKET, 0.0)

    series: dict[str, np.ndarray] = {}
    used_proxy, unpriced = [], []
    for sym in by_symbol:
        for cand in dict.fromkeys([proxy_for[sym], bench["class_proxies"].get(sym_class[sym]) or ""]):
            if not cand:
                continue
            try:
                r = daily_returns(closes_fn(cand))
            except Exception:
                r = np.array([])
            if len(r) >= 20:
                series[sym] = r
                if cand != sym:
                    used_proxy.append(f"{sym} via {cand}")
                break
        else:
            unpriced.append(sym)
    covered = sum(by_symbol[k] for k in series)
    out["coverage"] = {"priced_pct": (covered + cash) / total, "unpriced": sorted(unpriced), "proxied": sorted(used_proxy), "cash_pct": cash / total}
    if not series:
        out["notes"].append("No price history available, so only the historical stress tests could be run.")
        return out

    w = {k: by_symbol[k] / (covered + cash) for k in series}  # weights over everything we can price, cash included at 0 return/0 vol
    n = min(len(v) for v in series.values())
    port = portfolio_returns(series, w) if w else np.array([])
    cash_w = cash / (covered + cash)
    port = port * (1 - cash_w)  # cash contributes a flat zero return
    out["risk"] = stats(port, total, cfg["var_confidence"], cfg["trading_days_per_year"])
    try:
        mkt = daily_returns(closes_fn(market_symbol))
        out["risk"]["beta"] = qe.beta(port, mkt) if len(mkt) > 20 else None
    except Exception:
        out["risk"]["beta"] = None

    syms = sorted(w, key=lambda k: -w[k])
    mat = np.vstack([series[k][-n:] for k in syms])
    cov = np.cov(mat, ddof=1) * cfg["trading_days_per_year"]
    cov = np.atleast_2d(cov)
    wv = np.array([w[k] for k in syms])  # already scaled so weights + cash sum to 1
    rc = risk_contribution(wv, cov)
    out["contribution"] = [{"symbol": k, "weight": float(wv[i]), "risk_share": float(rc[i])} for i, k in enumerate(syms)][:15]
    top = syms[: cfg["max_correlation_names"]]
    out["correlation"] = qe.correlation_matrix({k: series[k] for k in top}) if len(top) >= 2 else {}
    out["notes"].append("Uses today's weights over the available price history; it is not your realized history. Cash is counted at zero risk.")
    return out
