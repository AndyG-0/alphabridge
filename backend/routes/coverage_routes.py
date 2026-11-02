from flask import Blueprint, jsonify, request
from pydantic import ValidationError

import db
from models import CoverageOption
from routes._helpers import get_profile
from schemas import CoverageChoiceIn, CoverageOptionIn
from services import household

bp = Blueprint("coverage", __name__, url_prefix="/api")


def _check_drug(s, data: dict, own_id: int | None):
    """A drug add-on must be one of this user's DRUG rows (user scoping applies through the query)."""
    did = data.get("drug_option_id")
    if did is None:
        return None
    d = s.get(CoverageOption, did)
    if d is None or d.category != "DRUG" or did == own_id:
        return "drug_option_id must be an existing DRUG option"
    return None


def _payload():
    try:
        return CoverageOptionIn.model_validate(request.get_json(force=True)).model_dump(), None
    except ValidationError as e:
        return None, (jsonify(error=e.errors(include_url=False, include_context=False)), 422)


@bp.get("/coverage-options")
def coverage_list():
    s = db.session()
    opts = s.query(CoverageOption).order_by(CoverageOption.sort_order, CoverageOption.id).all()
    return jsonify(options=[o.to_dict() for o in opts], choice=get_profile().coverage_choice or {})


@bp.post("/coverage-options")
def coverage_create():
    data, err = _payload()
    if err:
        return err
    s = db.session()
    if msg := _check_drug(s, data, None):
        return jsonify(error=msg), 422
    o = CoverageOption(**data)
    s.add(o)
    s.commit()
    return jsonify(o.to_dict()), 201


@bp.put("/coverage-options/<int:oid>")
def coverage_update(oid):
    data, err = _payload()
    if err:
        return err
    s = db.session()
    o = s.get(CoverageOption, oid)
    if o is None:
        return jsonify(error="not found"), 404
    if msg := _check_drug(s, data, oid):
        return jsonify(error=msg), 422
    for k, v in data.items():
        setattr(o, k, v)
    s.commit()
    return jsonify(o.to_dict())


@bp.delete("/coverage-options/<int:oid>")
def coverage_delete(oid):
    s = db.session()
    o = s.get(CoverageOption, oid)
    if o is None:
        return jsonify(error="not found"), 404
    profile = get_profile()
    choice = {k: v for k, v in (profile.coverage_choice or {}).items() if v != oid}
    profile.coverage_choice = choice
    for other in s.query(CoverageOption).filter(CoverageOption.drug_option_id == oid):
        other.drug_option_id = None  # SQLite does not enforce ON DELETE SET NULL unless foreign_keys is on
    s.delete(o)
    s.commit()
    return "", 204


@bp.put("/coverage-choice")
def coverage_choice():
    try:
        body = CoverageChoiceIn.model_validate(request.get_json(force=True))
    except ValidationError as e:
        return jsonify(error=e.errors(include_url=False, include_context=False)), 422
    s = db.session()
    profile = get_profile()
    choice = dict(profile.coverage_choice or {})
    people = {p.key for p in household.people(profile)}
    for key in body.model_fields_set:
        oid = getattr(body, key)
        if oid is None:
            choice.pop(key, None)
            continue
        o = s.get(CoverageOption, oid)
        if o is None or o.category == "DRUG":
            return jsonify(error=f"{key}: unknown or drug-only option"), 422
        if key not in people:
            return jsonify(error=f"{key}: no such person on the profile"), 422
        choice[key] = oid
    profile.coverage_choice = choice
    s.commit()
    return jsonify(choice=choice)
