from flask import Blueprint, jsonify, request
from pydantic import ValidationError

import db
from models import SpendingGoal
from routes._helpers import get_profile
from schemas import SpendingGoalIn
from services import household, planner
from services import spending as spending_svc
from services import spending_goals as goals_svc

bp = Blueprint("spending_goals", __name__, url_prefix="/api")


def _payload():
    try:
        return SpendingGoalIn.model_validate(request.get_json(force=True)).model_dump(), None
    except ValidationError as e:
        return None, (jsonify(error=e.errors(include_url=False, include_context=False)), 422)


def goals_summary() -> dict:
    """Goals plus lifetime cost by goal; shared with the chat tool."""
    profile = get_profile()
    goals = db.session().query(SpendingGoal).order_by(SpendingGoal.sort_order, SpendingGoal.id).all()
    ppl = household.people(profile)
    ages = {p.key: p.age_now for p in ppl}
    retire_years = household.year_index(profile.target_retirement_age - profile.current_age)
    years = max(int(95 - profile.current_age), 1)
    smodel = spending_svc.load(getattr(profile, "spending_model", None))
    sm = goals_svc.summarize(goals, ages, retire_years, years, smodel)
    return {"goals": [g.to_dict() for g in goals], "costs": sm["goals"], **{k: sm[k] for k in ("lifetime_real", "lifetime_nominal", "rows")}}


@bp.get("/spending-goals")
def goals_list():
    return jsonify(goals_summary())


@bp.get("/spending-goals/presets")
def goals_presets():
    return jsonify(goals_svc.presets())


@bp.get("/spending-goals/impact")
def goals_impact():
    return jsonify(planner.spending_goals_impact(get_profile(), n_sims=int(request.args.get("n_sims", 2000))))


@bp.post("/spending-goals")
def goals_create():
    data, err = _payload()
    if err:
        return err
    s = db.session()
    g = SpendingGoal(**data)
    s.add(g)
    s.commit()
    return jsonify(g.to_dict()), 201


@bp.put("/spending-goals/<int:gid>")
def goals_update(gid):
    data, err = _payload()
    if err:
        return err
    s = db.session()
    g = s.get(SpendingGoal, gid)
    if g is None:
        return jsonify(error="not found"), 404
    for k, v in data.items():
        setattr(g, k, v)
    s.commit()
    return jsonify(g.to_dict())


@bp.delete("/spending-goals/<int:gid>")
def goals_delete(gid):
    s = db.session()
    g = s.get(SpendingGoal, gid)
    if g is None:
        return jsonify(error="not found"), 404
    s.delete(g)
    s.commit()
    return "", 204
