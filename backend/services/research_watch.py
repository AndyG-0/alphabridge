"""Read logic for the watchlist, thesis tracker, DCF grid and insider signal, shared by the research routes and the chat tools."""

from datetime import date

from models import ThesisRecord, WatchlistItem
from services import market_data
from services import research_extras as rx


def watch_values(sym: str) -> tuple[float | None, float | None]:
    f = market_data.get_fundamentals(sym)
    closes = market_data.get_closes(sym, "1y")
    price = closes[-1] if closes else None
    d = rx.dcf_sensitivity(f.get("free_cash_flow"), f.get("shares_outstanding"), f.get("revenue_growth"), price)
    return price, (d or {}).get("base")


def thesis_values(sym: str) -> dict:
    """Metrics a thesis can reference in invalidation criteria."""
    f = market_data.get_fundamentals(sym)
    closes = market_data.get_closes(sym, "1y")
    price = closes[-1] if closes else None
    vals = {k: f.get(k) for k in ("revenue_growth", "operating_margin", "debt_to_equity", "free_cash_flow", "trailing_pe")}
    vals["price"] = price
    if closes and price:
        vals["drawdown_from_high"] = price / max(closes) - 1
    return vals


def watch_view(w: WatchlistItem, price: float | None, dcf_value: float | None) -> dict:
    item = {"id": w.id, "symbol": w.symbol, "note": w.note, "buy_below": w.buy_below, "upside_alert": w.upside_alert}
    return {**item, "price": price, "dcf_value": dcf_value, "alerts": rx.watch_alerts(item, price, dcf_value, rx.rules()["watchlist"]["default_upside_alert"])}


def thesis_view(t: ThesisRecord, values: dict | None) -> dict:
    checks = rx.check_criteria(t.criteria_json, values) if values is not None else [{**c, "current": None, "triggered": None} for c in t.criteria_json]
    return {
        "id": t.id,
        "symbol": t.symbol,
        "thesis": t.thesis,
        "status": t.status,
        "invalidated_on": t.invalidated_on.isoformat() if t.invalidated_on else None,
        "criteria": checks,
        "broken": [c for c in checks if c["triggered"]],
    }


def watchlist_view(s) -> list[dict]:
    out = []
    for w in s.query(WatchlistItem).order_by(WatchlistItem.symbol).all():
        try:
            price, dv = watch_values(w.symbol)
        except Exception:
            price, dv = None, None
        out.append(watch_view(w, price, dv))
    return out


def theses_view(s) -> list[dict]:
    out = []
    for t in s.query(ThesisRecord).order_by(ThesisRecord.created_at.desc()).all():
        try:
            vals = thesis_values(t.symbol) if t.status == "ACTIVE" else None
        except Exception:
            vals = None
        out.append(thesis_view(t, vals))
    return out


def dcf_for(sym: str) -> dict | None:
    f = market_data.get_fundamentals(sym)
    closes = market_data.get_closes(sym, "1y")
    out = rx.dcf_sensitivity(f.get("free_cash_flow"), f.get("shares_outstanding"), f.get("revenue_growth"), closes[-1] if closes else None)
    return None if out is None else {"symbol": sym, **out}


def insiders_for(sym: str, identity: str) -> dict:
    trades = market_data.insider_transactions(sym, identity)
    return {"symbol": sym, **rx.insider_signal(trades, date.today()), "institutional": rx.institutional_signal({}, {})}
