"""3-stage discovery: quant screener -> macro/sector overlay -> EDGAR deep dive with LLM narrative."""

import contextlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field

import db
from models import Account, ResearchReport, ScreenerResult
from services import market_data as md
from services import quant_engine as qe

# Compact default universe; extend via UNIVERSE env / settings later.
DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "AVGO",
    "TSLA",
    "LLY",
    "V",
    "MA",
    "COST",
    "NFLX",
    "AMD",
    "CRM",
    "ADBE",
    "NOW",
    "PANW",
    "ISRG",
    "UBER",
    "ANET",
    "CRWD",
    "DDOG",
    "SHOP",
    "MELI",
    "TTD",
    "ABNB",
    "VRTX",
    "REGN",
    "TMO",
    "SYK",
    "CAT",
    "DE",
    "ETN",
    "PWR",
    "GE",
    "FTNT",
    "SNPS",
    "CDNS",
    "LRCX",
    "KLAC",
    "TSM",
]

GRADES = ["A", "B", "C", "D", "F"]


def screen_one(f: dict, closes: list[float]) -> dict | None:
    """Apply the deterministic quality/growth filters. Returns metrics dict with pass flag and 0-100 score."""
    rg, de, fcf = f.get("revenue_growth"), f.get("debt_to_equity"), f.get("free_cash_flow")
    mn, mp = f.get("margin_now"), f.get("margin_prev")
    arr = closes
    m = {
        "revenue_growth": rg,
        "debt_to_equity": de,
        "fcf": fcf,
        "margin_expanding": (mn is not None and mp is not None and mn > mp),
        "operating_margin": f.get("operating_margin"),
        "rsi14": qe.rsi(arr) if len(arr) > 15 else None,
        "sma200_dist": qe.sma_distance(arr, 200) if len(arr) >= 200 else None,
        "pe": f.get("trailing_pe"),
        "sector": f.get("sector"),
        "name": f.get("name"),
    }
    checks = {
        "growth": rg is not None and rg > 0.12,
        "margin": m["margin_expanding"],
        "leverage": de is not None and de < 1.5,
        "fcf": fcf is not None and fcf > 0,
    }
    m["checks"] = checks
    m["passed"] = all(checks.values())
    rsi_v, d = m["rsi14"], m["sma200_dist"]
    parts = {
        "growth": (30 * min(max((rg or 0) / 0.40, 0), 1), 30),
        "margin": (20 if checks["margin"] else 0, 20),
        "leverage": (15 * (1 - min(max((de if de is not None else 3) / 1.5, 0), 1)), 15),
        "fcf": (15 if checks["fcf"] else 0, 15),
        # prefer not overbought; reward constructive pullbacks
        "rsi": (10 * (1 - min(abs(rsi_v - 50) / 30, 1)) if rsi_v is not None else 0, 10),
        "trend": ((10 if -0.05 <= d <= 0.25 else 3) if d is not None else 0, 10),
    }
    score = sum(v for v, _ in parts.values())
    m["score_breakdown"] = {k: {"points": round(v, 1), "max": mx} for k, (v, mx) in parts.items()}
    m["score"] = round(score, 1)
    return m


def _ret(closes: list[float], days: int) -> float | None:
    return closes[-1] / closes[-days - 1] - 1 if len(closes) > days else None


def symbol_detail(symbol: str) -> dict:
    """Everything the UI shows when drilling into one ticker. Deterministic; no LLM."""
    import numpy as np

    symbol = symbol.upper()
    f = md.get_fundamentals(symbol)
    closes = md.get_closes(symbol, "2y")
    if not closes:
        raise LookupError(f"No price data for {symbol}")
    arr = np.asarray(closes, float)
    spy = md.get_closes("SPY", "2y")
    daily = np.diff(arr) / arr[:-1]
    b = None
    if len(closes) > 60 and len(spy) > 60:
        n = min(len(closes), len(spy))
        b = qe.beta(np.diff(closes[-n:]) / np.asarray(closes[-n:-1]), np.diff(spy[-n:]) / np.asarray(spy[-n:-1]))
    year = arr[-252:]
    fcf, shares, growth = f.get("free_cash_flow"), f.get("shares_outstanding"), f.get("revenue_growth")
    dcf = None
    if fcf and fcf > 0 and shares and growth is not None:
        with contextlib.suppress(ValueError):
            dcf = qe.simple_dcf(fcf, min(max(growth, 0.0), 0.30), shares=shares)
    price = closes[-1]
    s = db.session()
    rep = s.query(ResearchReport).filter_by(symbol=symbol).order_by(ResearchReport.created_at.desc()).first()
    exposure = portfolio_exposure()
    held = exposure["names"].get(symbol, 0.0)
    step = max(-(-len(closes[-252:]) // 52), 1)
    return {
        "symbol": symbol,
        "fundamentals": f,
        "screen": screen_one(f, closes),
        "price": price,
        "technicals": {
            "ret_1m": _ret(closes, 21),
            "ret_3m": _ret(closes, 63),
            "ret_1y": _ret(closes, 252),
            "volatility": float(daily.std(ddof=1) * np.sqrt(252)) if len(daily) > 2 else None,
            "max_drawdown_1y": qe.max_drawdown(year),
            "beta": b,
            "high_52w": float(year.max()),
            "low_52w": float(year.min()),
        },
        "dcf_value": dcf,
        "dcf_upside": (dcf / price - 1) if dcf and price else None,
        "held_weight": held,
        "sector_weight": exposure["sectors"].get(f.get("sector") or "Unknown", 0.0),
        "price_series": [round(c, 2) for c in closes[-252:][::step]],
        "report": None
        if rep is None
        else {
            "id": rep.id,
            "recommended_action": rep.recommended_action,
            "valuation_grade": rep.valuation_grade,
            "growth_grade": rep.growth_grade,
            "moat_grade": rep.moat_grade,
            "bull_case_md": rep.bull_case_md,
            "bear_case_md": rep.bear_case_md,
            "created_at": rep.created_at.isoformat(),
            "portfolio_fit_notes": rep.portfolio_fit_notes,
            "red_flags": (rep.metrics_json or {}).get("red_flags", []),
        },
    }


def run_screener(universe: list[str] | None = None, top_n: int = 10) -> list[dict]:
    results = []
    for sym in universe or DEFAULT_UNIVERSE:
        try:
            f = md.get_fundamentals(sym)
            closes = md.get_closes(sym, "2y")
            m = screen_one(f, closes)
        except Exception:
            continue
        if m:
            results.append({"symbol": sym, **m})
    results.sort(key=lambda r: (r["passed"], r["score"]), reverse=True)
    s = db.session()
    now = datetime.now(UTC)
    for r in results[: max(top_n * 2, 20)]:
        s.add(ScreenerResult(run_at=now, symbol=r["symbol"], score=r["score"], metrics_json=r))
    s.commit()
    return results[:top_n]


def apply_macro_overlay(candidates: list[dict], sectors: list[dict]) -> list[dict]:
    """Boost candidates in sectors with strong relative strength (simple sector-name -> ETF map)."""
    sector_map = {
        "Technology": "XLK",
        "Healthcare": "XLV",
        "Industrials": "XLI",
        "Energy": "XLE",
        "Financial Services": "XLF",
        "Consumer Cyclical": "XLY",
        "Consumer Defensive": "XLP",
        "Utilities": "XLU",
        "Communication Services": "XLK",
    }
    rank = {s["etf"]: i for i, s in enumerate(sectors)}
    n = max(len(sectors), 1)
    for c in candidates:
        etf = sector_map.get(c.get("sector") or "")
        if etf in rank:
            tailwind = 1 - rank[etf] / max(n - 1, 1)  # 1 = strongest
            c["sector_etf"], c["sector_tailwind"] = etf, round(tailwind, 2)
            c["score"] = round(c["score"] * (0.9 + 0.2 * tailwind), 1)
    return sorted(candidates, key=lambda r: r["score"], reverse=True)


def portfolio_exposure(extra_symbol: str | None = None, extra_amount: float = 0.0) -> dict:
    """Sector + single-name exposure incl. look-through for index funds, with optional hypothetical add."""
    s = db.session()
    sector_dollars: dict[str, float] = {}
    name_dollars: dict[str, float] = {}
    total = 0.0
    for a in s.query(Account).all():
        for h in a.holdings:
            total += h.market_value
            sym = h.proxy_ticker or h.symbol
            if h.asset_class in ("MONEY_MARKET", "BOND"):
                sector_dollars["Cash/Bonds"] = sector_dollars.get("Cash/Bonds", 0) + h.market_value
                continue
            if h.asset_class == "INDIVIDUAL_STOCK":
                f = _safe_fund(sym)
                sec = (f or {}).get("sector") or "Unknown"
                sector_dollars[sec] = sector_dollars.get(sec, 0) + h.market_value
                name_dollars[sym] = name_dollars.get(sym, 0) + h.market_value
                continue
            top = md.get_etf_holdings(sym) if sym.isalpha() else {}
            covered = 0.0
            for hs, w in top.items():
                dollars = h.market_value * w
                covered += dollars
                name_dollars[hs] = name_dollars.get(hs, 0) + dollars
                sec = (_safe_fund(hs) or {}).get("sector") or "Unknown"
                sector_dollars[sec] = sector_dollars.get(sec, 0) + dollars
            rest = h.market_value - covered
            sector_dollars["Diversified"] = sector_dollars.get("Diversified", 0) + rest
    if extra_symbol and extra_amount > 0:
        total_after = total  # funded from existing cash: total unchanged, cash shrinks
        f = _safe_fund(extra_symbol) or {}
        sec = f.get("sector") or "Unknown"
        sector_dollars[sec] = sector_dollars.get(sec, 0) + extra_amount
        sector_dollars["Cash/Bonds"] = max(sector_dollars.get("Cash/Bonds", 0) - extra_amount, 0)
        name_dollars[extra_symbol] = name_dollars.get(extra_symbol, 0) + extra_amount
        total = total_after
    return {"total": total, "sectors": qe.concentration(sector_dollars, total), "names": qe.concentration(name_dollars, total)}


def _safe_fund(sym: str) -> dict | None:
    try:
        return md.get_fundamentals(sym)
    except Exception:
        return None


def concentration_warnings(before: dict, after: dict, limit: float) -> list[str]:
    out = []
    for sec, w in after["sectors"].items():
        if sec in ("Cash/Bonds", "Diversified", "Unknown"):
            continue
        if w > limit and w > before["sectors"].get(sec, 0):
            out.append(f"This raises {sec} exposure to {w:.0%}, above your {limit:.0%} limit.")
    for nm, w in after["names"].items():
        if w > 0.10 and w > before["names"].get(nm, 0):
            out.append(f"{nm} would be {w:.0%} of your portfolio (single-name > 10%).")
    return out


class Citation(BaseModel):
    form: str
    section: str
    quote: str = Field(description="Short verbatim excerpt from the provided filing text")


class Thesis(BaseModel):
    valuation_grade: str = Field(description="A-F")
    growth_grade: str
    moat_grade: str
    bull_case_md: str
    bear_case_md: str
    red_flags: list[str] = []
    citations: list[Citation] = []
    recommended_action: str = Field(description="BUY_SATELLITE | WATCHLIST | AVOID | HOLD_MMF")


THESIS_SYSTEM = (
    "You are an equity research analyst. You receive PRE-COMPUTED metrics and SEC filing excerpts. "
    "Do NOT calculate or invent numbers; only cite figures present in the input. Quotes must be verbatim "
    "from the provided filing text. Grade A-F. Be balanced; flag risk-factor changes and red flags."
)


def deep_dive(symbol: str, trigger: str, fred_key: str, edgar_identity: str, metrics: dict | None = None, llm=None, edgar=None) -> ResearchReport:
    """Stage 3. `llm` / `edgar` injectable for tests."""
    symbol = symbol.upper()
    if metrics is None:
        metrics = screen_one(md.get_fundamentals(symbol), md.get_closes(symbol, "2y")) or {}
    edgar_ctx = (edgar or md.edgar_filing_context)(symbol, edgar_identity)
    s = db.session()
    profile_limit = _limit()
    before = portfolio_exposure()
    after = portfolio_exposure(symbol, min(before["total"] * 0.02, 10000) or 0)
    warns = concentration_warnings(before, after, profile_limit)
    if llm is None:
        from services.llm_router import complete_structured

        llm = lambda sys, usr: complete_structured("reasoning", sys, usr, Thesis)
    payload = {
        "symbol": symbol,
        "quant_metrics": metrics,
        "portfolio_flags": warns,
        "filing": edgar_ctx["citation"],
        "risk_factors_excerpt": edgar_ctx["risk_factors"],
        "mdna_excerpt": edgar_ctx["mdna"],
        "financial_statements": edgar_ctx["financials"],
    }
    thesis: Thesis = llm(THESIS_SYSTEM, json.dumps(payload, default=str))
    action = thesis.recommended_action if thesis.recommended_action in ("BUY_SATELLITE", "WATCHLIST", "AVOID", "HOLD_MMF") else "WATCHLIST"
    if warns and action == "BUY_SATELLITE":
        action = "WATCHLIST"  # deterministic guardrail overrides the model
    rep = ResearchReport(
        symbol=symbol,
        trigger_source=trigger,
        quant_score=metrics.get("score", 0),
        valuation_grade=thesis.valuation_grade,
        growth_grade=thesis.growth_grade,
        moat_grade=thesis.moat_grade,
        bull_case_md=thesis.bull_case_md,
        bear_case_md=thesis.bear_case_md,
        sec_filing_citations_json=[{**edgar_ctx["citation"], **c.model_dump()} for c in thesis.citations],
        portfolio_fit_notes=" ".join(warns) or "No concentration issues detected.",
        recommended_action=action,
        metrics_json={**metrics, "red_flags": thesis.red_flags},
    )
    s.add(rep)
    s.commit()
    return rep


def _limit() -> float:
    from routes._helpers import get_profile

    return get_profile().sector_concentration_limit


def what_if(symbol: str, amount: float, source: str = "MMF") -> dict:
    """Deterministic what-if: portfolio exposure change, beta, fundamentals. No LLM."""
    symbol = symbol.upper()
    before = portfolio_exposure()
    after = portfolio_exposure(symbol, amount)
    f = _safe_fund(symbol) or {}
    closes = md.get_closes(symbol, "2y")
    spy = md.get_closes("SPY", "2y")
    b = None
    if len(closes) > 60 and len(spy) > 60:
        import numpy as np

        n = min(len(closes), len(spy))
        b = qe.beta(np.diff(closes[-n:]) / closes[-n:-1], np.diff(spy[-n:]) / spy[-n:-1])
    total = before["total"] or 1.0
    port_beta = _portfolio_beta()
    new_beta = port_beta + (amount / total) * ((b if b is not None else 1.0) - 0.0) if port_beta is not None else None
    return {
        "symbol": symbol,
        "amount": amount,
        "asset_beta": b,
        "fundamentals": f,
        "portfolio_beta_before": port_beta,
        "portfolio_beta_after": new_beta,
        "sector_before": before["sectors"],
        "sector_after": after["sectors"],
        "warnings": concentration_warnings(before, after, _limit()),
        "screen": screen_one(f, closes) if f else None,
    }


def _portfolio_beta() -> float | None:
    s = db.session()
    w = {"US_EQUITY": 1.0, "INTL_EQUITY": 0.9, "SECTOR_ETF": 1.1, "INDIVIDUAL_STOCK": 1.2, "BOND": 0.1, "MONEY_MARKET": 0.0}
    tot = b = 0.0
    for a in s.query(Account).all():
        for h in a.holdings:
            tot += h.market_value
            b += h.market_value * w.get(h.asset_class, 1.0)
    return b / tot if tot else None
