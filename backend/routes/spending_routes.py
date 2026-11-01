import io

from flask import Blueprint, jsonify, request

import db
from models import CategoryRule, Transaction
from routes._helpers import get_profile
from security import safe_filename, validate_upload
from services import transactions
from services.llm_router import LLMNotConfigured

bp = Blueprint("spending", __name__, url_prefix="/api")


def _tx(t: Transaction) -> dict:
    return {
        "id": t.id,
        "date": t.tx_date.isoformat(),
        "description": t.description,
        "amount": t.amount,
        "account": t.account_label,
        "category": t.category,
        "source": t.category_source,
        "suggested_category": t.suggested_category,
    }


@bp.get("/spending/actuals")
def actuals():
    return jsonify(transactions.actuals(get_profile(), months=request.args.get("months", 12, type=int)))


@bp.get("/spending/transactions")
def list_transactions():
    q = db.session().query(Transaction)
    if request.args.get("uncategorized") == "1":
        q = q.filter(Transaction.category == "")
    rows = q.order_by(Transaction.tx_date.desc(), Transaction.id.desc()).limit(min(request.args.get("limit", 100, type=int), 500)).all()
    return jsonify({"categories": transactions.categories(), "transactions": [_tx(t) for t in rows]})


@bp.post("/spending/import")
def import_file():
    f = request.files.get("file")
    if not f:
        return jsonify(error="file required"), 400
    name = safe_filename(f.filename or "transactions.csv")
    data = f.read()
    if bad := validate_upload(name, data):
        return jsonify(error=bad), 415
    items, errs = transactions.parse_csv(io.BytesIO(data).read().decode("utf-8-sig", errors="replace"))
    if not items:
        return jsonify(error="No transactions found", row_errors=errs), 422
    if request.form.get("dry_run") == "1":
        return jsonify(preview=True, count=len(items), row_errors=errs, sample=[{**i, "tx_date": i["tx_date"].isoformat()} for i in items[:20]]), 200
    return jsonify({**transactions.import_rows(items), "row_errors": errs}), 201


@bp.post("/spending/transactions/<int:tid>/category")
def set_category(tid: int):
    body = request.get_json(silent=True) or {}
    try:
        ok = transactions.set_category(tid, str(body.get("category", "")), bool(body.get("make_rule")))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return (jsonify(ok=True), 200) if ok else (jsonify(error="not found"), 404)


@bp.post("/spending/suggest")
def suggest():
    try:
        return jsonify(suggested=transactions.suggest_with_llm())
    except LLMNotConfigured as e:
        return jsonify(error=str(e)), 409
    except ValueError as e:
        return jsonify(error=str(e)), 422


@bp.post("/spending/confirm")
def confirm():
    ids = [int(i) for i in (request.get_json(silent=True) or {}).get("ids", [])]
    return jsonify(confirmed=transactions.confirm_suggestions(ids))


@bp.get("/spending/rules")
def list_rules():
    return jsonify([{"id": r.id, "pattern": r.pattern, "category": r.category} for r in db.session().query(CategoryRule).order_by(CategoryRule.pattern)])


@bp.post("/spending/rules")
def add_rule():
    body = request.get_json(silent=True) or {}
    pat, cat = str(body.get("pattern", "")).strip().lower()[:120], str(body.get("category", ""))
    if not pat or cat not in transactions.categories():
        return jsonify(error="pattern and a valid category required"), 400
    s = db.session()
    r = s.query(CategoryRule).filter_by(pattern=pat).first() or CategoryRule(pattern=pat, category=cat)
    r.category = cat
    s.add(r)
    s.commit()
    return jsonify(recategorized=transactions.recategorize_uncategorized()), 201


@bp.post("/spending/apply-to-plan")
def apply_to_plan():
    """Opt-in: set the profile's current monthly expenses to the measured average. Requires an explicit confirm flag."""
    if not (request.get_json(silent=True) or {}).get("confirm"):
        return jsonify(error="confirm: true required; this overwrites monthly_expenses_current"), 400
    a = transactions.actuals(get_profile())
    if not a["months_used"]:
        return jsonify(error="No complete months of spending to average"), 422
    p = get_profile()
    before = p.monthly_expenses_current
    p.monthly_expenses_current = a["measured_monthly_avg"]
    db.session().commit()
    return jsonify(before=before, after=p.monthly_expenses_current, months_used=a["months_used"])
