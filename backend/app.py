import hmac
import logging

from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import ValidationError

import db
from config import Config
from observability import configure_logging, init_observability
from security import client_key, init_security

log = logging.getLogger("alphabridge")


def _is_share(path: str) -> bool:
    """Signed-token report links; the route verifies the token itself."""
    return path.startswith("/api/share/") and path.endswith((".csv", ".pdf"))


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.update(overrides or {})
    if app.config["CORS_ORIGINS"]:
        CORS(app, origins=app.config["CORS_ORIGINS"])
    if not app.config.get("TESTING"):
        configure_logging(app.config["LOG_LEVEL"], app.config["LOG_FORMAT"])
    init_observability(app)
    limiter = init_security(app)
    # Migrate on every start (also on the debug reloader's restarts); tests build their schema with create_all instead.
    db.init_db(app.config["DATABASE_URL"], auto_migrate=not app.config.get("TESTING"))
    with app.app_context():
        from routes._helpers import get_profile

        get_profile()  # ensure the default single-user profile exists

    @app.before_request
    def _auth():
        token = app.config["ACCESS_TOKEN"]
        if not token or request.method == "OPTIONS" or request.path in ("/api/health", "/api/ready") or _is_share(request.path):
            return None
        who = client_key()
        if limiter.blocked(who):
            return jsonify(error="too many failed attempts; try again later"), 429
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            limiter.record_failure(who)
            return jsonify(error="unauthorized"), 401
        return None

    @app.before_request
    def _user():
        raw = request.headers.get("X-AlphaBridge-User", "").strip()
        if not raw:
            return None
        from flask import g

        from models import UserProfile

        if not raw.isdigit() or db.session().get(UserProfile, int(raw)) is None:
            return jsonify(error="unknown user"), 400
        g.user_id = int(raw)
        return None

    @app.teardown_appcontext
    def _cleanup(_exc):
        db.remove_session()

    @app.errorhandler(ValidationError)
    def _validation(e):
        return jsonify(error="validation", details=e.errors(include_url=False, include_context=False)), 400

    @app.errorhandler(Exception)
    def _unhandled(e):
        from werkzeug.exceptions import HTTPException

        if isinstance(e, HTTPException):
            return jsonify(error=e.description), e.code
        log.exception("unhandled error")
        return jsonify(error=str(e)), 500

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    import importlib

    for mod in (
        "portfolio_routes",
        "planner_routes",
        "research_routes",
        "settings_routes",
        "chat_routes",
        "liability_routes",
        "pension_routes",
        "coverage_routes",
        "spending_goals_routes",
        "early_access_routes",
        "tax_routes",
        "rmd_routes",
        "spending_routes",
        "export_routes",
        "onboarding_routes",
        "chart_routes",
        "action_routes",
        "user_routes",
    ):
        app.register_blueprint(importlib.import_module(f"routes.{mod}").bp)

    if app.config["ENABLE_SCHEDULER"]:
        from services.scheduler import start_scheduler

        start_scheduler(app)
    return app


app = None


def get_app():
    global app
    if app is None:
        app = create_app()
    return app
