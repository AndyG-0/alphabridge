"""Cached yfinance + FRED + EDGAR access. Everything network-bound lives here so it can be mocked."""

import contextlib
import logging
import time
from datetime import UTC, datetime, timedelta

import requests

import db
from models import MarketCache
from services.cash_optimizer import MarketInputs

SECTOR_ETFS = ["XLK", "XLV", "XLI", "XLE", "XLF", "SMH", "XLY", "XLP", "XLU"]
_last_call = 0.0
MISS_TTL = 3600  # empty fund look-through results are retried after an hour


def _throttle(min_gap=0.25):
    global _last_call
    wait = min_gap - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def cache_get(key: str, ttl_seconds: int):
    row = db.session().get(MarketCache, key)
    if row is None:
        return None
    fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=UTC)
    if datetime.now(UTC) - fetched > timedelta(seconds=ttl_seconds):
        return None
    return row.payload


def cache_set(key: str, payload):
    s = db.session()
    row = s.get(MarketCache, key)
    if row is None:
        s.add(MarketCache(key=key, payload=payload))
    else:
        row.payload, row.fetched_at = payload, datetime.now(UTC)
    s.commit()


def get_closes(symbol: str, period: str = "2y", ttl: int = 6 * 3600) -> list[float]:
    key = f"px:{symbol}:{period}"
    hit = cache_get(key, ttl)
    if hit is not None:
        return hit
    import yfinance as yf

    _throttle()
    hist = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    closes = [float(x) for x in hist["Close"].dropna().tolist()]
    if closes:
        cache_set(key, closes)
    return closes


def fx_rate(currency: str) -> float | None:
    """USD per one unit of `currency` (cached via the price cache); None if it can't be fetched."""
    cur = currency.strip().upper()
    if cur in ("", "USD"):
        return 1.0
    try:
        closes = get_closes(f"{cur}USD=X", period="5d", ttl=6 * 3600)
    except Exception:
        return None
    return closes[-1] if closes else None


def get_quote(symbol: str) -> dict:
    closes = get_closes(symbol, "1y")
    return {"symbol": symbol, "price": closes[-1] if closes else None}


def get_fundamentals(symbol: str, ttl: int = 24 * 3600) -> dict:
    key = f"fund:{symbol}"
    hit = cache_get(key, ttl)
    if hit is not None:
        return hit
    import yfinance as yf

    _throttle()
    t = yf.Ticker(symbol)
    info = t.info or {}
    margin_now = margin_prev = None
    try:
        inc = t.income_stmt
        rev = inc.loc["Total Revenue"].dropna()
        op = inc.loc["Operating Income"].dropna()
        if len(rev) >= 2 and len(op) >= 2:
            margin_now, margin_prev = float(op.iloc[0] / rev.iloc[0]), float(op.iloc[1] / rev.iloc[1])
    except Exception:
        pass
    de = info.get("debtToEquity")
    out = {
        "symbol": symbol,
        "name": info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "market_cap": info.get("marketCap"),
        "revenue_growth": info.get("revenueGrowth"),
        "operating_margin": info.get("operatingMargins"),
        "margin_now": margin_now,
        "margin_prev": margin_prev,
        "debt_to_equity": (de / 100.0) if de is not None else None,  # yfinance reports percent
        "free_cash_flow": info.get("freeCashflow"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "beta": info.get("beta"),
        "price": info.get("currentPrice"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "quote_type": info.get("quoteType"),
        "summary": info.get("longBusinessSummary"),
        "website": info.get("website"),
        "employees": info.get("fullTimeEmployees"),
        "dividend_yield": info.get("dividendYield"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "peg": info.get("trailingPegRatio"),
        "roe": info.get("returnOnEquity"),
        "gross_margin": info.get("grossMargins"),
        "profit_margin": info.get("profitMargins"),
        "current_ratio": info.get("currentRatio"),
        "target_price": info.get("targetMeanPrice"),
        "analyst_rating": info.get("recommendationKey"),
        "short_pct_float": info.get("shortPercentOfFloat"),
    }
    cache_set(key, out)
    return out


def get_fund_lookthrough(symbol: str, ttl: int = 7 * 24 * 3600) -> dict:
    """Live fund look-through (top holdings, sector weights, asset mix) from yfinance `funds_data`.

    Empty dicts when unavailable. An empty result is cached only MISS_TTL so a transient outage doesn't hide a fund for a week."""
    key = f"xray:fund:{symbol}"
    hit = cache_get(key, ttl)
    if hit is not None and (any(hit.values()) or cache_get(key, MISS_TTL) is not None):
        return hit
    out: dict = {"top_holdings": {}, "sectors": {}, "asset_mix": {}}
    try:
        import yfinance as yf

        _throttle()
        fd = yf.Ticker(symbol).funds_data
        with contextlib.suppress(Exception):
            out["top_holdings"] = {str(s): float(r["Holding Percent"]) for s, r in fd.top_holdings.iterrows()}
        with contextlib.suppress(Exception):
            out["sectors"] = {str(k): float(v) for k, v in (fd.sector_weightings or {}).items() if v}
        try:
            ac = fd.asset_classes or {}
            other = sum(float(ac.get(k) or 0) for k in ("preferredPosition", "convertiblePosition", "otherPosition"))
            mix = {"Cash": ac.get("cashPosition"), "Stocks": ac.get("stockPosition"), "Bonds": ac.get("bondPosition"), "Other": other}
            out["asset_mix"] = {k: float(v) for k, v in mix.items() if v}
        except Exception:
            pass
    except Exception:
        pass
    cache_set(key, out)
    return out


def get_etf_holdings(symbol: str, ttl: int = 7 * 24 * 3600) -> dict[str, float]:
    """Top holdings weights for look-through; {} if unavailable (an empty result is retried after MISS_TTL)."""
    key = f"etfh:{symbol}"
    hit = cache_get(key, ttl)
    if hit or (hit is not None and cache_get(key, MISS_TTL) is not None):
        return hit
    out: dict[str, float] = {}
    try:
        import yfinance as yf

        _throttle()
        df = yf.Ticker(symbol).funds_data.top_holdings
        for sym, row in df.iterrows():
            out[str(sym)] = float(row["Holding Percent"])
    except Exception:
        pass
    cache_set(key, out)
    return out


def _fred_latest(series: str, api_key: str, n: int = 1) -> list[float]:
    _throttle()
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        timeout=15,
        params={"series_id": series, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": n + 5},
    )
    r.raise_for_status()
    vals = [float(o["value"]) for o in r.json()["observations"] if o["value"] not in (".", "")]
    return vals[:n] if n > 1 else vals[:1]


def macro_snapshot(fred_key: str = "", ttl: int = 3600) -> dict:
    """Rates/CPI/VIX from FRED when a key exists, else yfinance proxies. Flags what was estimated."""
    key = "macro:v1"
    hit = cache_get(key, ttl)
    if hit is not None:
        return hit
    notes = []
    tbill = ten = vix = cpi = None
    if fred_key:
        try:
            tbill = _fred_latest("DTB3", fred_key)[0] / 100
            ten = _fred_latest("DGS10", fred_key)[0] / 100
            vix = _fred_latest("VIXCLS", fred_key)[0]
            cpis = _fred_latest("CPIAUCSL", fred_key, 13)
            cpi = cpis[0] / cpis[12] - 1
        except Exception:
            logging.getLogger(__name__).warning("FRED request failed", exc_info=True)
            notes.append("FRED unavailable; using Yahoo fallbacks")
    if tbill is None:
        tbill = (get_closes("^IRX", "5d", 3600) or [4.5])[-1] / 100
        notes.append("3M T-Bill from Yahoo ^IRX")
    if ten is None:
        ten = (get_closes("^TNX", "5d", 3600) or [4.2])[-1] / 100
    if vix is None:
        vix = (get_closes("^VIX", "5d", 3600) or [18.0])[-1]
    if cpi is None:
        cpi = 0.03
        notes.append("CPI defaulted to 3.0% (set FRED_API_KEY for live CPI)")
    spy = get_closes("SPY", "2y", 3600)
    vs200 = (spy[-1] / (sum(spy[-200:]) / 200) - 1) if len(spy) >= 200 else 0.0
    pe = get_fundamentals("SPY").get("trailing_pe") or 22.0
    out = {"tbill_3m": tbill, "ten_year": ten, "cpi_yoy": cpi, "sp500_pe": pe, "vix": vix, "sp500_vs_200dma": vs200, "notes": notes}
    cache_set(key, out)
    return out


def market_inputs(fred_key: str = "") -> tuple[MarketInputs, list[str]]:
    m = macro_snapshot(fred_key)
    return MarketInputs(**{k: m[k] for k in ("tbill_3m", "ten_year", "cpi_yoy", "sp500_pe", "vix", "sp500_vs_200dma")}), m["notes"]


def sector_strength(ttl: int = 6 * 3600) -> list[dict]:
    """3- and 6-month relative strength of sector ETFs vs SPY."""
    spy = get_closes("SPY", "1y", ttl)
    out = []
    for etf in SECTOR_ETFS:
        c = get_closes(etf, "1y", ttl)
        if len(c) < 130 or len(spy) < 130:
            continue
        r3, r6 = c[-1] / c[-63] - 1, c[-1] / c[-126] - 1
        s3, s6 = spy[-1] / spy[-63] - 1, spy[-1] / spy[-126] - 1
        out.append({"etf": etf, "ret_3m": r3, "ret_6m": r6, "rel_3m": r3 - s3, "rel_6m": r6 - s6, "score": 0.5 * (r3 - s3) + 0.5 * (r6 - s6)})
    return sorted(out, key=lambda x: x["score"], reverse=True)


def edgar_filing_context(ticker: str, identity: str, max_chars: int = 12000) -> dict:
    """Latest 10-K risk factors + MD&A text and filing citation via edgartools."""
    from edgar import Company, set_identity

    set_identity(identity)
    co = Company(ticker)
    filings = co.get_filings(form=["10-K", "10-Q"])
    filing = filings.latest()
    cite = {
        "form": filing.form,
        "filing_date": str(filing.filing_date),
        "accession": filing.accession_no,
        "url": getattr(filing, "filing_url", None) or getattr(filing, "homepage_url", None),
    }
    risk = mdna = ""
    try:
        doc = filing.obj()
        risk = str(getattr(doc, "risk_factors", "") or "")[:max_chars]
        mdna = str(getattr(doc, "management_discussion", "") or "")[:max_chars]
    except Exception:
        pass
    fin_text = ""
    try:
        fin = co.get_financials()
        fin_text = "\n\n".join(str(x) for x in (fin.income_statement(), fin.balance_sheet(), fin.cashflow_statement()))[:8000]
    except Exception:
        pass
    return {"citation": cite, "risk_factors": risk, "mdna": mdna, "financials": fin_text}


def insider_transactions(ticker: str, identity: str, limit: int = 25) -> list[dict]:
    """Recent Form 4 open-market rows [{date, insider, code, shares, price}] via edgartools. Any parse problem returns what was read."""
    from edgar import Company, set_identity

    set_identity(identity)
    rows: list[dict] = []
    for filing in list(Company(ticker).get_filings(form="4").head(limit)):
        try:
            f4 = filing.obj()
            df = f4.market_trades
            for _, r in df.iterrows():
                rows.append(
                    {
                        "date": str(r.get("Date") or r.get("date") or filing.filing_date)[:10],
                        "insider": str(getattr(f4, "insider_name", "") or ""),
                        "code": str(r.get("Code") or r.get("code") or "")[:1],
                        "shares": float(r.get("Shares") or r.get("shares") or 0),
                        "price": float(r.get("Price") or r.get("price") or 0),
                    }
                )
        except Exception:
            continue
    return rows
