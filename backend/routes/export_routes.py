"""Data ownership routes: JSON export/import, CSV/PDF plan report, encrypted backup, read-only share links.

`/api/share/<token>/...` is the only unauthenticated-by-bearer prefix (see app._auth); the signed token scopes it to the report.
"""

from flask import Blueprint, Response, abort, current_app, jsonify, request

import db
from services import export

bp = Blueprint("export", __name__, url_prefix="/api")

_ATTACH = 'attachment; filename="{}"'


def _report(fmt: str):
    d = export.report_data()
    if fmt == "csv":
        return Response(export.report_csv(d), mimetype="text/csv", headers={"Content-Disposition": _ATTACH.format("alphabridge-report.csv")})
    if fmt == "pdf":
        return Response(
            export.make_pdf(export.report_lines(d)), mimetype="application/pdf", headers={"Content-Disposition": _ATTACH.format("alphabridge-report.pdf")}
        )
    return abort(404)


@bp.get("/export/report.<fmt>")
def report(fmt):
    return _report(fmt)


@bp.get("/export/json")
def export_json():
    body = export.export_json(db.session())
    return Response(__import__("json").dumps(body), mimetype="application/json", headers={"Content-Disposition": _ATTACH.format("alphabridge-export.json")})


@bp.post("/export/import")
def import_json():
    payload = request.get_json(force=True)
    if payload.get("confirm") is not True:
        return jsonify(error="importing replaces ALL data; send confirm=true"), 400
    s = db.session()
    try:
        counts = export.import_json(s, payload.get("data") or {})
        s.commit()
    except ValueError:
        s.rollback()
        return jsonify(error="not a valid AlphaBridge export for this version"), 400
    return jsonify(imported=counts)


@bp.post("/export/share")
def make_share():
    days = int((request.get_json(silent=True) or {}).get("days", 7))
    return jsonify(export.make_share_token(days))


@bp.post("/export/backup")
def run_backup():
    if not export.destination():
        return jsonify(error="set BACKUP_DEST (local, webdav or s3) first"), 400
    try:
        return jsonify(path=export.run_backup(db.session()))
    except Exception:  # destination errors are logged server-side, not echoed
        current_app.logger.exception("backup failed")
        return jsonify(error="backup failed; see the server log"), 502


@bp.get("/share/<token>/report.<fmt>")
def shared_report(token, fmt):
    if not export.verify_share_token(token):
        abort(404)
    return _report(fmt)
