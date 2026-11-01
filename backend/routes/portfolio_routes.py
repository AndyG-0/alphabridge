import re
from datetime import date

from flask import Blueprint, jsonify, request
from pydantic import BaseModel, Field, field_validator

import db
from models import Account, AllowedPlanMenu, CashFlow, Holding, IngestionLog, Liability, TaxLot
from routes._helpers import get_profile
from schemas import AccountIn, ConfirmedIngest, PlanMenuItemIn, ProfileIn, ProxyMapIn
from security import safe_filename, validate_upload
from services import corporate_actions, doc_reader, ingestion, institutions, market_data, networth, performance, rebalance, tax_lots, xray

bp = Blueprint("portfolio", __name__, url_prefix="/api")


def holding_dict(h: Holding) -> dict:
    return {
        c: getattr(h, c)
        for c in ("id", "account_id", "symbol", "name", "shares", "cost_basis_total", "current_price", "market_value", "asset_class", "proxy_ticker")
    } | {"last_updated": h.last_updated.isoformat() if h.last_updated else None}


def account_dict(a: Account, with_holdings=True) -> dict:
    d = {c: getattr(a, c) for c in ("id", "name", "institution", "tax_bucket", "risk_tier", "is_restricted_plan", "owner", "is_current_employer_plan")}
    d["total"] = sum(h.market_value for h in a.holdings)
    d["bucket"] = ingestion.classify_account(a)
    if with_holdings:
        d["holdings"] = [holding_dict(h) for h in a.holdings]
    return d


@bp.get("/institutions")
def institutions_list():
    return jsonify(institutions.INSTITUTIONS)


@bp.get("/profile")
def profile_get():
    p = get_profile()
    return jsonify(p.to_dict())


@bp.put("/profile")
def profile_put():
    raw = request.get_json(force=True)
    data = ProfileIn.model_validate(raw).model_dump(exclude_none=True)
    if "spouse_birth_date" in raw and raw["spouse_birth_date"] is None:
        data["spouse_birth_date"] = None  # explicit null clears the spouse
    p = get_profile()
    for k, v in data.items():
        setattr(p, k, v)
    db.session().commit()
    return profile_get()


@bp.get("/portfolio")
def portfolio():
    s = db.session()
    accounts = s.query(Account).order_by(Account.id).all()
    t = ingestion.bucket_totals(s)
    debt = sum(liab.balance for liab in s.query(Liability).all())
    return jsonify(
        accounts=[account_dict(a) for a in accounts],
        buckets=t,
        assets=sum(t.values()),
        liabilities=debt,
        net_worth=sum(t.values()) - debt,
        by_owner=ingestion.owner_totals(s),
    )


@bp.post("/accounts")
def account_create():
    data = AccountIn.model_validate(request.get_json(force=True))
    s = db.session()
    # fields the client omitted are inferred from the name via the institution registry
    attrs = ingestion._default_account_attrs(data.name) | data.model_dump(include=data.model_fields_set)
    a = Account(name=data.name, **{k: v for k, v in attrs.items() if k != "name"})
    s.add(a)
    s.commit()
    return jsonify(account_dict(a)), 201


@bp.put("/accounts/<int:aid>")
def account_update(aid):
    data = AccountIn.model_validate(request.get_json(force=True))
    s = db.session()
    a = s.get(Account, aid)
    if a is None:
        return jsonify(error="not found"), 404
    for k, v in data.model_dump().items():
        setattr(a, k, v)
    # plan flags follow the account type so a retype can't leave a stale restricted-plan / Rule-of-55 flag
    is_401k = a.tax_bucket == "PRE_TAX_401K"
    a.is_restricted_plan = is_401k
    if not is_401k:
        a.is_current_employer_plan = False
    s.commit()
    return jsonify(account_dict(a))


@bp.delete("/accounts/<int:aid>")
def account_delete(aid):
    s = db.session()
    a = s.get(Account, aid)
    if a:
        s.query(IngestionLog).filter(IngestionLog.account_id == aid).delete()
        s.delete(a)
        s.flush()
        ingestion.snapshot_net_worth(s)
        s.commit()
    return "", 204


@bp.delete("/holdings/<int:hid>")
def holding_delete(hid):
    s = db.session()
    h = s.get(Holding, hid)
    if h:
        s.delete(h)
        s.flush()
        ingestion.snapshot_net_worth(s)
        s.commit()
    return "", 204


def _row_dict(r: ingestion.ParsedRow) -> dict:
    return {
        "symbol": r.symbol,
        "name": r.name,
        "shares": r.shares,
        "price": r.price,
        "market_value": r.market_value,
        "asset_class": r.asset_class,
        "account_name": r.account_name,
        "needs_mapping": r.needs_mapping,
    }


def _confirmed_result(raw: str) -> ingestion.ParseResult:
    """Rows the user reviewed (and possibly edited) in the preview; re-validated, never trusted blindly."""
    body = ConfirmedIngest.model_validate_json(raw)
    res = ingestion.ParseResult(parser="pdf_llm_confirmed", source=body.source, warnings=["Reviewed and confirmed by user"])
    for r in body.rows:
        sym = r.symbol.strip().upper()
        res.rows.append(
            ingestion.ParsedRow(
                symbol=sym,
                name=r.name or sym,
                shares=r.shares,
                price=r.price or (r.market_value / r.shares if r.shares else 0),
                market_value=r.market_value,
                asset_class=r.asset_class,
                account_name=(r.account_name or "").strip() or None,
                needs_mapping=not re.fullmatch(r"[A-Z]{1,5}", sym) and r.asset_class != "MONEY_MARKET",
            )
        )
    return res


@bp.post("/ingest")
def ingest():
    """CSV / known PDFs import immediately. OCR/AI-read documents return a preview (nothing written) that the
    client confirms by re-posting the reviewed rows as `rows` JSON."""
    f = request.files.get("file")
    confirmed = request.form.get("rows")
    if not f and not confirmed:
        return jsonify(error="file required"), 400
    account_id = request.form.get("account_id", type=int)
    owner = request.form.get("owner") or None
    if owner not in (None, "SELF", "SPOUSE", "JOINT"):
        return jsonify(error="owner must be SELF, SPOUSE or JOINT"), 400
    name = safe_filename((f.filename if f else request.form.get("filename")) or "upload")
    try:
        if confirmed:
            result = _confirmed_result(confirmed)
        else:
            data, low = f.read(), name.lower()
            if bad := validate_upload(name, data):
                return jsonify(error=bad), 415
            if low.endswith(".pdf"):
                result = ingestion.parse_pdf(data)
            elif low.endswith(doc_reader.IMAGE_EXTS):
                result = ingestion.parse_image(data)
            else:
                text = data.decode("utf-8-sig", errors="replace")
                if ingestion.is_lot_export(text):
                    return jsonify(error="This is a lot-level cost-basis export. Use 'Import tax lots' so it isn't read as positions."), 422
                result = ingestion.parse_csv(text)
    except Exception as e:
        s = db.session()
        s.add(IngestionLog(filename=name, account_id=account_id, status="ERROR", message=str(e)[:500]))
        s.commit()
        return jsonify(error=f"Could not parse {name}: {e}"), 422
    if result.pension:
        if any(c["level"] == "fail" for c in result.checks):
            return jsonify(error="The statement's arithmetic doesn't add up; nothing was imported.", checks=result.checks), 422
        try:
            pension_owner = ingestion.resolve_pension_owner(result.pension, get_profile(), owner)
        except ingestion.AmbiguousOwner as e:
            return jsonify(error=f"Whose pension is this? The statement is for {e.name}.", needs_owner=True, owners=e.owners), 409
        except ValueError as e:
            return jsonify(error=str(e)), 400
        return jsonify(ingestion.apply_pension(result, name, pension_owner)), 201
    if not result.rows:
        return jsonify(error="No holdings found in file", warnings=result.warnings, row_errors=result.row_errors), 422
    if result.needs_review or request.form.get("dry_run") == "1":
        return jsonify(
            preview=True,
            parser=result.parser,
            source=result.source,
            confidence=result.confidence,
            checks=result.checks,
            warnings=result.warnings,
            filename=name,
            row_errors=result.row_errors,
            rows=[_row_dict(r) for r in result.rows],
        ), 200
    if account_id is None:
        try:
            ingestion.resolve_accounts(result, owner)
        except ingestion.AmbiguousOwner as e:
            return jsonify(error=str(e), needs_owner=True, owners=e.owners), 409
    if request.form.get("allow_duplicate") != "1":
        dup = ingestion.find_duplicate(result, exclude_account_id=account_id)
        if dup is not None and not (account_id is None and _names_match(result, dup, owner)):
            return jsonify(
                error=f"This looks like a duplicate of '{dup.name}', which already holds the same data.",
                duplicate_of={"id": dup.id, "name": dup.name},
                diff=ingestion.diff_against_account(result, dup),
            ), 409
    return jsonify(ingestion.apply_parse(result, name, account_id, owner)), 201


def _names_match(result, acct: Account, owner: str | None = None) -> bool:
    """Auto-detect imports that name the same account (and owner, when given) replace it in place;
    that's an update, not a duplicate."""
    if owner and acct.owner != owner:
        return False
    return bool(result.rows) and all(r.account_name == acct.name for r in result.rows)


@bp.get("/portfolio/xray")
def portfolio_xray():
    return jsonify(xray.portfolio_xray())


@bp.get("/ingest/log")
def ingest_log():
    s = db.session()
    rows = s.query(IngestionLog).order_by(IngestionLog.id.desc()).limit(50).all()
    names = {a.id: a.name for a in s.query(Account).all()}
    return jsonify(
        [
            {
                "id": r.id,
                "filename": r.filename,
                "parser": r.parser,
                "rows": r.rows_parsed,
                "status": r.status,
                "message": r.message,
                "created_at": r.created_at.isoformat(),
                "account_id": r.account_id,
                "account": names.get(r.account_id),
                "batch_id": r.batch_id,
                "content_hash": r.content_hash[:12],
                "can_undo": ingestion.can_undo(s, r),
                "undone_at": r.undone_at.isoformat() if r.undone_at else None,
            }
            for r in rows
        ]
    )


@bp.post("/ingest/<int:log_id>/undo")
def ingest_undo(log_id):
    try:
        return jsonify(ingestion.undo_import(db.session(), log_id))
    except LookupError as e:
        return jsonify(error=str(e)), 404
    except ValueError as e:
        return jsonify(error=str(e)), 409


class SplitIn(BaseModel):
    ratio: float


class SpinoffIn(BaseModel):
    symbol: str
    shares: float
    basis_fraction: float
    price: float = 0.0
    name: str = ""


@bp.post("/holdings/<int:hid>/split")
def holding_split(hid):
    s = db.session()
    h = s.get(Holding, hid)
    if h is None:
        return jsonify(error="holding not found"), 404
    body = SplitIn.model_validate(request.get_json(force=True))
    try:
        out = corporate_actions.split(h, body.ratio)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    s.commit()
    return jsonify(out)


@bp.post("/holdings/<int:hid>/spinoff")
def holding_spinoff(hid):
    s = db.session()
    h = s.get(Holding, hid)
    if h is None:
        return jsonify(error="holding not found"), 404
    b = SpinoffIn.model_validate(request.get_json(force=True))
    try:
        out = corporate_actions.spinoff(s, h, b.symbol, b.shares, b.basis_fraction, b.price, b.name)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    s.flush()
    ingestion.snapshot_net_worth(s)
    s.commit()
    return jsonify(out), 201


@bp.get("/networth/history")
def networth_history():
    return jsonify(networth.history(db.session()))


@bp.get("/networth/summary")
def networth_summary():
    return jsonify(networth.summary(db.session(), get_profile()))


class CashFlowIn(BaseModel):
    on: date
    amount: float
    note: str = Field(default="", max_length=200)

    @field_validator("amount")
    @classmethod
    def _nonzero(cls, v: float) -> float:
        if v == 0:
            raise ValueError("amount must be non-zero")
        return v


def flow_dict(f: CashFlow) -> dict:
    return {"id": f.id, "on": f.on.isoformat(), "amount": f.amount, "note": f.note}


@bp.get("/cashflows")
def cashflows_list():
    return jsonify([flow_dict(f) for f in db.session().query(CashFlow).order_by(CashFlow.on)])


@bp.post("/cashflows")
def cashflows_add():
    body = CashFlowIn.model_validate(request.get_json(silent=True) or {})
    s = db.session()
    f = CashFlow(on=body.on, amount=body.amount, note=body.note)
    s.add(f)
    s.commit()
    return jsonify(flow_dict(f)), 201


@bp.delete("/cashflows/<int:fid>")
def cashflows_delete(fid):
    s = db.session()
    f = s.get(CashFlow, fid)
    if f is None:
        return jsonify({"error": "not found"}), 404
    s.delete(f)
    s.commit()
    return "", 204


def performance_report(assume: bool) -> dict:
    return performance.report(db.session(), get_profile(), market_data.get_closes, market_data.get_fundamentals, assume_contributions=assume)


@bp.get("/performance")
def performance_get():
    return jsonify(performance_report(request.args.get("assume_contributions") in ("1", "true")))


def _lot_context(s):
    from datetime import date as _date

    today = _date.today()
    accounts = {a.id: a for a in s.query(Account).all()}
    prices = {(h.account_id, h.symbol): h.current_price for h in s.query(Holding).all() if h.current_price}
    lots = s.query(TaxLot).order_by(TaxLot.symbol, TaxLot.acquired).all()
    return today, accounts, lots, [tax_lots.lot_view(lot, prices, today) for lot in lots]


@bp.get("/tax-lots")
def tax_lots_report():
    return jsonify(tax_lots.report(db.session(), get_profile()))


@bp.get("/tax-lots/list")
def tax_lots_list():
    _, accounts, _, views = _lot_context(db.session())
    return jsonify([v | {"account": accounts[v["account_id"]].name} for v in views])


@bp.get("/tax-lots/sell")
def tax_lots_sell():
    symbol = (request.args.get("symbol") or "").strip()
    try:
        amount = float(request.args.get("amount", ""))
    except ValueError:
        return jsonify({"error": "amount (dollars) is required"}), 400
    if not symbol or amount <= 0:
        return jsonify({"error": "symbol and a positive amount are required"}), 400
    today, accounts, lots, views = _lot_context(db.session())
    return jsonify(tax_lots.suggest_sale(views, symbol, amount, get_profile(), today, lots, accounts, request.args.get("account_id", type=int)))


@bp.post("/tax-lots/import")
def tax_lots_import():
    f = request.files.get("file")
    account_id = request.form.get("account_id", type=int)
    if not f or account_id is None:
        return jsonify(error="file and account_id are required"), 400
    s = db.session()
    if s.get(Account, account_id) is None:
        return jsonify(error="unknown account"), 404
    name = safe_filename(f.filename or "lots.csv")
    data = f.read()
    if bad := validate_upload(name, data):
        return jsonify(error=bad), 415
    parsed = ingestion.parse_lots(data.decode("utf-8-sig", errors="replace"))
    if not parsed.rows:
        return jsonify(error="No usable lots found.", row_errors=parsed.row_errors, warnings=parsed.warnings), 422
    return jsonify(ingestion.apply_lots(s, parsed, account_id)), 201


@bp.get("/rebalance")
def rebalance_get():
    try:
        threshold = float(request.args.get("threshold", rebalance.DEFAULT_THRESHOLD))
    except ValueError:
        return jsonify({"error": "threshold must be a number"}), 400
    if not 0 < threshold < 1:
        return jsonify({"error": "threshold must be between 0 and 1"}), 400
    return jsonify(rebalance.report(db.session(), get_profile(), threshold))


def menu_dict(m: AllowedPlanMenu) -> dict:
    return {c: getattr(m, c) for c in ("id", "account_id", "ticker_or_cusip", "fund_name", "asset_class", "expense_ratio", "benchmark_proxy_ticker")}


@bp.get("/accounts/<int:aid>/menu")
def menu_list(aid):
    rows = db.session().query(AllowedPlanMenu).filter_by(account_id=aid).all()
    return jsonify([menu_dict(m) for m in rows])


@bp.put("/accounts/<int:aid>/menu")
def menu_replace(aid):
    items = [PlanMenuItemIn.model_validate(i) for i in request.get_json(force=True)]
    s = db.session()
    s.query(AllowedPlanMenu).filter_by(account_id=aid).delete()
    for i in items:
        s.add(AllowedPlanMenu(account_id=aid, **i.model_dump()))
    s.commit()
    return menu_list(aid)


@bp.get("/holdings/unmapped")
def unmapped():
    """401(k) holdings whose symbol isn't a public ticker and has no proxy yet."""
    import re

    s = db.session()
    out = [
        holding_dict(h)
        for h in s.query(Holding).filter(Holding.proxy_ticker.is_(None))
        if h.asset_class != "MONEY_MARKET" and not re.fullmatch(r"[A-Z]{1,5}", h.symbol)
    ]
    return jsonify(out)


@bp.post("/holdings/map-proxy")
def map_proxy():
    data = ProxyMapIn.model_validate(request.get_json(force=True))
    s = db.session()
    h = s.get(Holding, data.holding_id)
    if not h:
        return jsonify(error="not found"), 404
    h.proxy_ticker = data.proxy_ticker.strip().upper()
    for m in s.query(AllowedPlanMenu).filter_by(account_id=h.account_id, ticker_or_cusip=h.symbol):
        m.benchmark_proxy_ticker = h.proxy_ticker
    s.commit()
    return jsonify(holding_dict(h))


class _ProxySuggestion(BaseModel):
    ticker: str
    rationale: str


@bp.post("/holdings/<int:hid>/suggest-proxy")
def suggest_proxy(hid):
    from services.llm_router import LLMNotConfigured, complete_structured

    h = db.session().get(Holding, hid)
    if not h:
        return jsonify(error="not found"), 404
    try:
        out = complete_structured(
            "fast",
            "Suggest the single best publicly traded mutual fund/ETF ticker that tracks the same strategy as this "
            "employer-plan fund (e.g. a Collective Investment Trust). If unsure, choose the closest broad index fund.",
            f"Fund name: {h.name}\nAsset class: {h.asset_class}",
            _ProxySuggestion,
        )
    except LLMNotConfigured as e:
        return jsonify(error=str(e)), 400
    return jsonify(ticker=out.ticker.upper(), rationale=out.rationale)
