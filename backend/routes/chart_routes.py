from datetime import date

from flask import Blueprint, jsonify, request

import db
from routes._helpers import get_profile
from services import chart_data

bp = Blueprint("charts", __name__, url_prefix="/api")


@bp.get("/charts/brackets")
def brackets():
    p = get_profile()
    magi = request.args.get("magi", type=float)
    if magi is None:
        magi = float(p.annual_income or 0) + float(p.spouse_annual_income or 0)
    return jsonify(chart_data.bracket_fill(magi, p.tax_filing_status, request.args.get("year", date.today().year, type=int)))


@bp.get("/charts/cashflow")
def cashflow():
    return jsonify(chart_data.cash_flow(db.session(), get_profile()))
