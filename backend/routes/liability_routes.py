from flask import Blueprint, jsonify, request

import db
from models import IngestionLog, Liability
from schemas import LiabilityIn
from security import safe_filename, validate_upload
from services import doc_reader, ingestion, institutions, liability_ingest

bp = Blueprint("liabilities", __name__, url_prefix="/api")


@bp.get("/liabilities")
def liability_list():
    return jsonify([x.to_dict() for x in db.session().query(Liability).order_by(Liability.id)])


@bp.post("/liabilities")
def liability_create():
    data = LiabilityIn.model_validate(request.get_json(force=True))
    s = db.session()
    x = Liability(**data.model_dump())
    s.add(x)
    s.flush()
    ingestion.snapshot_net_worth(s)
    s.commit()
    return jsonify(x.to_dict()), 201


@bp.put("/liabilities/<int:lid>")
def liability_update(lid):
    data = LiabilityIn.model_validate(request.get_json(force=True))
    s = db.session()
    x = s.get(Liability, lid)
    if x is None:
        return jsonify(error="not found"), 404
    for k, v in data.model_dump().items():
        setattr(x, k, v)
    s.flush()
    ingestion.snapshot_net_worth(s)
    s.commit()
    return jsonify(x.to_dict())


@bp.delete("/liabilities/<int:lid>")
def liability_delete(lid):
    s = db.session()
    x = s.get(Liability, lid)
    if x:
        s.delete(x)
        s.flush()
        ingestion.snapshot_net_worth(s)
        s.commit()
    return "", 204


@bp.get("/liabilities/help")
def liability_help():
    return jsonify(institutions.LIABILITY_DOCS)


@bp.post("/liabilities/ingest")
def liability_upload():
    f = request.files.get("file")
    if not f:
        return jsonify(error="file required"), 400
    name = safe_filename(f.filename)
    data = f.read()
    if bad := validate_upload(name, data):
        return jsonify(error=bad), 415
    try:
        if name.lower().endswith(".pdf"):
            result = liability_ingest.parse_pdf(data)
        elif name.lower().endswith(doc_reader.IMAGE_EXTS):
            result = liability_ingest.parse_image(data)
        else:
            result = liability_ingest.parse_csv(data.decode("utf-8-sig", errors="replace"))
    except Exception as e:
        s = db.session()
        s.add(IngestionLog(filename=name, status="ERROR", message=str(e)[:500]))
        s.commit()
        return jsonify(error=f"Could not parse {name}: {e}"), 422
    if not result.debts:
        return jsonify(error="No debts found in file", warnings=result.warnings), 422
    return jsonify(liability_ingest.apply_parse(result, name)), 201
