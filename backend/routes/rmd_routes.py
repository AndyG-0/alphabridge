from datetime import date

from flask import Blueprint, jsonify, request

import db
from models import Account
from routes._helpers import get_profile
from services import rmd as rmd_svc

bp = Blueprint("rmd", __name__, url_prefix="/api")


def _pretax_by_owner() -> dict[str, float]:
    out = {"SELF": 0.0, "SPOUSE": 0.0}
    for a in db.session().query(Account).filter(Account.tax_bucket == "PRE_TAX_401K"):
        out["SPOUSE" if a.owner == "SPOUSE" else "SELF"] += sum(h.market_value for h in a.holdings)
    return out


def report(profile, qcd_annual: float = 0.0, real_return: float = 0.03) -> dict:
    """RMD projection per person plus what the combined RMDs do to the household's bracket; shared by the route and the chat tool."""
    today = date.today()
    bal = _pretax_by_owner()
    people = [("SELF", profile.birth_date, profile.current_age, profile.spouse_age > 0)]
    if profile.spouse_birth_date:
        people.append(("SPOUSE", profile.spouse_birth_date, profile.spouse_age, True))
    out: list[dict] = []
    by_year: dict = {}
    for key, birth, age_now, has_spouse in people:
        other_age = profile.spouse_age if key == "SELF" else profile.current_age
        proj = rmd_svc.projection(
            bal[key],
            birth.year,
            today.year,
            real_return=real_return,
            qcd_annual=qcd_annual / len(people),
            spouse_age_now=int(other_age) if has_spouse and other_age else None,
            spouse_sole_beneficiary=has_spouse,
            age_now=int(age_now),
        )
        for r in proj["rows"]:
            by_year.setdefault(r["year"], {"rmd": 0.0, "qcd": 0.0})
            by_year[r["year"]]["rmd"] += r["rmd"]
            by_year[r["year"]]["qcd"] += r["qcd"]
        out.append({"owner": key, "pretax_balance": bal[key], **proj})
    ss_year = (profile.social_security_monthly + (profile.spouse_social_security_monthly if profile.spouse_birth_date else 0)) * 12
    status = getattr(profile, "tax_filing_status", "SINGLE")
    forced = None
    live = {y: v for y, v in by_year.items() if v["rmd"] > 0}
    if live:
        peak = max(live, key=lambda y: live[y]["rmd"])
        forced = {"year": peak, "rmd": live[peak]["rmd"], **rmd_svc.forced_bracket(live[peak]["rmd"], 0.0, ss_year, status, peak, qcd=live[peak]["qcd"])}
    return {
        "people": out,
        "household_by_year": [{"year": y, **v} for y, v in sorted(by_year.items()) if v["rmd"] > 0],
        "peak_year_bracket": forced,
        "qcd_limit": rmd_svc.qcd_limit(today.year),
        "retrieved_on": rmd_svc.retrieved_on(),
    }


@bp.get("/rmd")
def rmd_report():
    return jsonify(report(get_profile(), request.args.get("qcd", 0.0, type=float), request.args.get("return", 0.03, type=float)))


@bp.get("/rmd/inherited")
def rmd_inherited():
    try:
        out = rmd_svc.inherited_schedule(
            float(request.args["balance"]),
            int(request.args["beneficiary_age"]),
            int(request.args["death_year"]),
            request.args.get("owner_after_rbd") == "1",
            real_return=request.args.get("return", 0.03, type=float),
            eligible_designated=request.args.get("eligible") == "1",
        )
    except (KeyError, ValueError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(out)
