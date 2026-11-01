from datetime import date

from flask import Blueprint, jsonify, request

from routes._helpers import get_profile
from services import tax

bp = Blueprint("tax", __name__, url_prefix="/api")


def estimate(args: dict) -> dict:
    """Tax estimate for explicit amounts; anything omitted defaults from the profile (household wages, filing status, state). Shared with the chat tool."""
    p = get_profile()
    wages = (p.annual_income or 0) + (p.spouse_annual_income or 0)
    ordinary = args.get("ordinary")
    out = tax.total_tax(
        ordinary=float(wages if ordinary is None else ordinary),
        qualified=float(args.get("qualified") or 0),
        social_security=float(args.get("social_security") or 0),
        status=args.get("status") or p.tax_filing_status,
        year=int(args.get("year") or date.today().year),
        state=args.get("state") or p.state,
        state_flat_rate=float(args["state_flat_rate"]) if args.get("state_flat_rate") is not None else None,
    )
    return {**out, "retrieved_on": tax.retrieved_on().isoformat()}


@bp.get("/tax/estimate")
def tax_estimate():
    try:
        return jsonify(estimate(request.args.to_dict()))
    except ValueError:
        return jsonify(error="numeric query parameters expected"), 400
