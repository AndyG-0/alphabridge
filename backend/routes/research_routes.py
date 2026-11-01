from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, Field

import db
from models import ResearchReport, ScreenerResult, ThesisRecord, WatchlistItem
from services import market_data
from services import research_extras as rx
from services import research_pipeline as rp
from services import research_watch as rw
from services.llm_router import LLMNotConfigured

bp = Blueprint("research", __name__, url_prefix="/api/research")


class WhatIfIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    amount: float = Field(gt=0)


class DeepDiveIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)


def report_dict(r: ResearchReport) -> dict:
    return {c.name: (getattr(r, c.name).isoformat() if c.name == "created_at" else getattr(r, c.name)) for c in r.__table__.columns}


@bp.get("/reports")
def reports():
    rows = db.session().query(ResearchReport).order_by(ResearchReport.created_at.desc()).limit(30).all()
    return jsonify([report_dict(r) for r in rows])


@bp.get("/screener")
def screener_latest():
    s = db.session()
    last = s.query(ScreenerResult).order_by(ScreenerResult.run_at.desc()).first()
    if not last:
        return jsonify([])
    rows = s.query(ScreenerResult).filter_by(run_at=last.run_at).order_by(ScreenerResult.score.desc()).all()
    return jsonify([r.metrics_json for r in rows])


@bp.post("/screener/run")
def screener_run():
    top = rp.run_screener()
    top = rp.apply_macro_overlay(top, market_data.sector_strength())
    return jsonify(top)


@bp.get("/sectors")
def sectors():
    return jsonify(market_data.sector_strength())


@bp.get("/symbol/<sym>")
def symbol_detail(sym: str):
    if not sym.replace(".", "").replace("-", "").isalnum() or len(sym) > 10:
        return jsonify(error="Invalid symbol"), 400
    try:
        return jsonify(rp.symbol_detail(sym))
    except LookupError as e:
        return jsonify(error=str(e)), 404


@bp.post("/deep-dive")
def deep_dive():
    data = DeepDiveIn.model_validate(request.get_json(force=True))
    from services.llm_router import get_config

    budget = rx.TokenBudget(get_config().token_budget)
    try:
        rep = rp.deep_dive(data.symbol, "ON_DEMAND", current_app.config["FRED_API_KEY"], current_app.config["EDGAR_IDENTITY"], budget=budget)
    except LLMNotConfigured as e:
        return jsonify(error=str(e)), 400
    except rx.BudgetExceeded:
        return jsonify(error="Token budget for this research run is used up; raise it in Settings"), 429
    return jsonify(report_dict(rep)), 201


@bp.post("/what-if")
def what_if():
    data = WhatIfIn.model_validate(request.get_json(force=True))
    return jsonify(rp.what_if(data.symbol, data.amount))


def _bad_symbol(sym: str) -> bool:
    return not sym.replace(".", "").replace("-", "").isalnum() or len(sym) > 10


@bp.get("/dcf/<sym>")
def dcf(sym: str):
    """DCF value grid over growth x discount, so a single point estimate is never shown alone."""
    if _bad_symbol(sym):
        return jsonify(error="Invalid symbol"), 400
    out = rw.dcf_for(sym.upper())
    if out is None:
        return jsonify(error=f"{sym.upper()} has no positive free cash flow / share count / growth to project"), 404
    return jsonify(out)


@bp.get("/insiders/<sym>")
def insiders(sym: str):
    if _bad_symbol(sym):
        return jsonify(error="Invalid symbol"), 400
    try:
        return jsonify(rw.insiders_for(sym.upper(), current_app.config["EDGAR_IDENTITY"]))
    except Exception:
        current_app.logger.exception("insiders: SEC data unavailable")
        return jsonify(error="SEC data unavailable"), 503


class WatchIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    note: str = Field(default="", max_length=500)
    buy_below: float | None = Field(default=None, gt=0)
    upside_alert: float | None = Field(default=None, gt=0, lt=5)


class ThesisIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    thesis: str = Field(default="", max_length=4000)
    criteria: list[dict] = Field(default_factory=list, max_length=12)


@bp.get("/watchlist")
def watchlist():
    return jsonify(rw.watchlist_view(db.session()))


@bp.post("/watchlist")
def watchlist_add():
    data = WatchIn.model_validate(request.get_json(force=True))
    sym = data.symbol.upper()
    if _bad_symbol(sym):
        return jsonify(error="Invalid symbol"), 400
    s = db.session()
    w = s.query(WatchlistItem).filter_by(symbol=sym).first() or WatchlistItem(symbol=sym)
    w.note, w.buy_below, w.upside_alert = data.note, data.buy_below, data.upside_alert
    s.add(w)
    s.commit()
    return jsonify(rw.watch_view(w, None, None)), 201


@bp.delete("/watchlist/<int:wid>")
def watchlist_delete(wid: int):
    s = db.session()
    w = s.get(WatchlistItem, wid)
    if w is None:
        return jsonify(error="not found"), 404
    s.delete(w)
    s.commit()
    return "", 204


@bp.get("/theses")
def theses():
    return jsonify(rw.theses_view(db.session()))


@bp.post("/theses")
def theses_add():
    data = ThesisIn.model_validate(request.get_json(force=True))
    if _bad_symbol(data.symbol):
        return jsonify(error="Invalid symbol"), 400
    for c in data.criteria:
        if c.get("op") not in rx.OPS or not isinstance(c.get("value"), (int, float)) or not c.get("metric"):
            return jsonify(error="each criterion needs metric, op (<, <=, >, >=) and numeric value"), 400
    s = db.session()
    t = ThesisRecord(symbol=data.symbol.upper(), thesis=data.thesis, criteria_json=data.criteria)
    s.add(t)
    s.commit()
    return jsonify(rw.thesis_view(t, None)), 201


@bp.delete("/theses/<int:tid>")
def theses_close(tid: int):
    s = db.session()
    t = s.get(ThesisRecord, tid)
    if t is None:
        return jsonify(error="not found"), 404
    t.status = "CLOSED"
    s.commit()
    return "", 204
