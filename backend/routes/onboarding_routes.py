from flask import Blueprint, jsonify, request

import db
from routes._helpers import get_profile
from schemas import OnboardingIn
from services import onboarding

bp = Blueprint("onboarding", __name__, url_prefix="/api")


@bp.get("/onboarding")
def get_onboarding():
    return jsonify(onboarding.status(db.session(), get_profile()))


@bp.put("/onboarding")
def put_onboarding():
    data = OnboardingIn.model_validate(request.get_json(force=True))
    return jsonify(onboarding.update(db.session(), get_profile(), **data.model_dump()))
