from flask import Blueprint, jsonify, request

import db
from routes._helpers import get_profile
from services import actions

bp = Blueprint("actions", __name__, url_prefix="/api")


@bp.get("/actions")
def list_actions():
    return jsonify(actions.feed(db.session(), get_profile(), include_hidden=request.args.get("all") == "1"))


def _set(key: str, status: str, days: int = 7):
    actions.mark(db.session(), get_profile(), key, status, days)
    return jsonify(ok=True)


@bp.post("/actions/<path:key>/snooze")
def snooze(key: str):
    days = (request.get_json(silent=True) or {}).get("days", 7)
    if not isinstance(days, int) or not 1 <= days <= 365:
        return jsonify(error="days must be an integer from 1 to 365"), 400
    return _set(key, "snoozed", days)


@bp.post("/actions/<path:key>/done")
def done(key: str):
    return _set(key, "done")


@bp.post("/actions/<path:key>/reopen")
def reopen(key: str):
    return _set(key, "open")
