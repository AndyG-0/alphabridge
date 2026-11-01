"""Structured JSON logs with per-request IDs, plus /api/ready and scheduler status."""

import contextvars
import json
import logging
import sys
import time
import uuid

from flask import Flask, g, jsonify, request
from sqlalchemy import func, text

import db
from models import MarketCache

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    from security import RedactingFilter

    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())  # redact at the handler so every logger, including third-party ones, is covered
    root.handlers = [handler]


def init_observability(app: Flask) -> None:
    @app.before_request
    def _rid():
        rid = request.headers.get("X-Request-ID", "")
        g.request_id = rid[:64] if rid.replace("-", "").isalnum() and rid else uuid.uuid4().hex[:16]
        request_id_var.set(g.request_id)
        g.t0 = time.perf_counter()

    @app.after_request
    def _log(resp):
        resp.headers["X-Request-ID"] = g.get("request_id", "-")
        if request.path != "/api/health":  # health probes would drown everything else
            logging.getLogger("alphabridge.access").info(
                "%s %s -> %s in %.0fms", request.method, request.path, resp.status_code, (time.perf_counter() - g.get("t0", time.perf_counter())) * 1000
            )
        return resp

    @app.get("/api/ready")
    def ready():
        checks: dict[str, dict] = {}
        try:
            db.session().execute(text("SELECT 1"))
            checks["database"] = {"ok": True}
        except Exception as e:
            checks["database"] = {"ok": False, "error": type(e).__name__}
        sched = app.extensions.get("scheduler")
        if app.config["ENABLE_SCHEDULER"]:
            checks["scheduler"] = {"ok": bool(sched and sched.running), "jobs": len(sched.get_jobs()) if sched else 0}
        else:
            checks["scheduler"] = {"ok": True, "disabled": True}
        try:
            last = db.session().query(func.max(MarketCache.fetched_at)).scalar()
            checks["market_data"] = {"ok": True, "last_refresh": last.isoformat() if last else None}  # informational: never blocks readiness
        except Exception as e:
            checks["market_data"] = {"ok": False, "error": type(e).__name__}
        ok = checks["database"]["ok"] and checks["scheduler"]["ok"]
        return jsonify(status="ready" if ok else "degraded", checks=checks), 200 if ok else 503

    @app.get("/api/scheduler/status")
    def scheduler_status():
        from services import scheduler

        sched = app.extensions.get("scheduler")
        jobs = [{"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None} for j in (sched.get_jobs() if sched else [])]
        return jsonify(enabled=bool(app.config["ENABLE_SCHEDULER"]), running=bool(sched and sched.running), jobs=jobs, history=scheduler.RUNS)
