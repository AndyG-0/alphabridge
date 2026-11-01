from flask import Blueprint, jsonify, request
from sqlalchemy import func

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
    # Explicit id: user 1 is created with id=1, which leaves a Postgres sequence behind, so autoincrement would collide.
    u = UserProfile(id=(s.query(func.max(UserProfile.id)).scalar() or 0) + 1, name=name)
    s.add(u)
    s.commit()
    return jsonify(id=u.id, name=u.name), 201
