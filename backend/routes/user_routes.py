from flask import Blueprint, jsonify, request

import db
from models import UserProfile

bp = Blueprint("users", __name__, url_prefix="/api")


@bp.post("/users")
def create_user():
    """Add another household member. Send their id as `X-AlphaBridge-User` to act as them; requests without it act as user 1."""
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()[:80]
    if not name:
        return jsonify(error="name is required"), 400
    s = db.session()
    u = UserProfile(name=name)
    s.add(u)
    s.commit()
    return jsonify(id=u.id, name=u.name), 201
