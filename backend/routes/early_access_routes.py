from flask import Blueprint, jsonify, request

import db
from models import Account
from routes._helpers import get_profile
from services import early_access as ea

bp = Blueprint("early_access", __name__, url_prefix="/api")


def _person(profile, owner: str):
    spouse = owner == "SPOUSE"
    birth = profile.spouse_birth_date if spouse else profile.birth_date
    retire = (profile.spouse_target_retirement_age or profile.target_retirement_age) if spouse else profile.target_retirement_age
    return birth, retire


def accounts_report(profile) -> list[dict]:
    """Pre-tax accounts with penalty-free access dates; shared by the route and the chat tool."""
    accounts = []
    for a in db.session().query(Account).filter(Account.tax_bucket == ea.PRETAX).order_by(Account.id):
        birth, retire = _person(profile, a.owner)
        access = ea.account_access(a, birth, retire, a.is_current_employer_plan)
        accounts.append(
            {
                "id": a.id,
                "name": a.name,
                "owner": a.owner,
                "balance": sum(h.market_value for h in a.holdings),
                "is_current_employer_plan": a.is_current_employer_plan,
                **access,
                "rollover": ea.rollover_advice(access, a.is_current_employer_plan),
            }
        )
    return accounts


@bp.get("/early-access")
def early_access():
    accounts = accounts_report(get_profile())
    return jsonify(accounts=accounts, exceptions=ea.exceptions(), penalty_rate=0.10, retrieved_on=ea.retrieved_on().isoformat())


@bp.get("/early-access/sepp")
def sepp():
    try:
        out = ea.sepp_payment(
            float(request.args["balance"]),
            int(request.args["age"]),
            float(request.args.get("rate", 0.05)),
            request.args.get("method", "amortization"),
            request.args.get("table", "single"),
            request.args.get("mid_term_rate", type=float),
        )
    except (KeyError, ValueError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(out)


@bp.post("/early-access/roth-order")
def roth_order():
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(
            ea.roth_ordering(
                float(b.get("contributions", 0)),
                [{"year": int(c["year"]), "amount": float(c["amount"])} for c in b.get("conversions", [])],
                float(b.get("earnings", 0)),
                float(b["withdraw"]),
                float(b["age"]),
                int(b["year"]),
                int(b["roth_open_year"]),
            )
        )
    except (KeyError, ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
