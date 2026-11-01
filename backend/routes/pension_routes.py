from flask import Blueprint, jsonify, request

import db
from models import Pension
from routes._helpers import get_profile
from schemas import PensionIn
from services import household
from services import pension as pension_svc

bp = Blueprint("pension", __name__, url_prefix="/api")


def _with_projection(p: Pension, profile) -> dict:
    person = next((x for x in household.people(profile) if x.key == p.owner), None)
    proj = pension_svc.projection(p, person.age_now, person.retire_age) if person else None
    return p.to_dict() | {"projection": proj}


@bp.get("/pensions")
def pension_list():
    profile = get_profile()
    return jsonify([_with_projection(p, profile) for p in db.session().query(Pension).order_by(Pension.owner)])


@bp.put("/pensions/<int:pid>")
def pension_update(pid):
    data = PensionIn.model_validate(request.get_json(force=True))
    s = db.session()
    p = s.get(Pension, pid)
    if p is None:
        return jsonify(error="not found"), 404
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    s.commit()
    return jsonify(_with_projection(p, get_profile()))


@bp.delete("/pensions/<int:pid>")
def pension_delete(pid):
    s = db.session()
    p = s.get(Pension, pid)
    if p is None:
        return jsonify(error="not found"), 404
    s.delete(p)
    s.commit()
    return "", 204
