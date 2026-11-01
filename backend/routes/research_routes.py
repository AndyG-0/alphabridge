from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, Field

import db
from models import ResearchReport, ScreenerResult
from services import market_data
from services import research_pipeline as rp
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
    try:
        rep = rp.deep_dive(data.symbol, "ON_DEMAND", current_app.config["FRED_API_KEY"], current_app.config["EDGAR_IDENTITY"])
    except LLMNotConfigured as e:
        return jsonify(error=str(e)), 400
    return jsonify(report_dict(rep)), 201


@bp.post("/what-if")
def what_if():
    data = WhatIfIn.model_validate(request.get_json(force=True))
    return jsonify(rp.what_if(data.symbol, data.amount))
