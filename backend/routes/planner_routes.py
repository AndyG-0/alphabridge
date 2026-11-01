from datetime import date
from types import SimpleNamespace

from flask import Blueprint, current_app, jsonify, request

import db
from models import Account, AllowedPlanMenu, Liability, PlannedEvent, Scenario
from routes._helpers import get_profile
from routes.portfolio_routes import holding_dict
from schemas import PlannedEventIn, ScenarioIn
from services import assumptions as assumptions_svc
from services import cash_backtest, cash_plan, market_data, planner, quant_engine
from services import ladder as ladder_svc
from services import liabilities as liab_svc
from services import roth as roth_svc
from services import scenarios as scen_svc
from services import spending as spending_svc
from services import withdrawal_strategies as ws_svc
from services import withdrawals as withdrawals_svc

bp = Blueprint("planner", __name__, url_prefix="/api")


# what-if query params -> (profile field, min, max)
WHAT_IF = {
    "retire_age": ("target_retirement_age", 30, 75),
    "spouse_retire_age": ("spouse_target_retirement_age", 0, 75),
    "spend": ("monthly_expenses_retirement", 0, 100_000),
    "ss_claim_age": ("ss_claim_age", 62, 70),
    "spouse_ss_claim_age": ("spouse_ss_claim_age", 62, 70),
    "target": ("target_success_rate", 0.5, 0.99),
}


@bp.get("/planner/fire")
def fire():
    p = get_profile()
    sims = request.args.get("sims", 5000, type=int)
    overrides = {}
    for arg, (col, lo, hi) in WHAT_IF.items():
        v = request.args.get(arg, type=float)
        if v is not None:
            overrides[col] = min(max(v, lo), hi)
    if overrides:
        p = SimpleNamespace(**(p.to_dict() | overrides))
    g = request.args.get("guardrails")
    res = planner.run_fire(p, n_sims=min(max(sims, 200), 20000), rule_of_55=request.args.get("rule55") == "1", guardrails=None if g is None else g == "1")
    return jsonify(res)


@bp.get("/planner/withdrawals")
def withdrawals():
    p = get_profile()
    names = [x for x in request.args.get("strategies", "").split(",") if x] or list(withdrawals_svc.STRATEGIES)
    bad = [x for x in names if x not in withdrawals_svc.STRATEGIES]
    if bad:
        return jsonify(error=f"unknown strategies: {bad}"), 400
    age = request.args.get("retire_age", type=float)
    return jsonify(planner.withdrawal_plan(p, names, detail=request.args.get("detail", "1") != "0", retire_age=age))


@bp.get("/planner/roth")
def roth():
    names = [x for x in request.args.get("modes", "").split(",") if x] or list(roth_svc.MODES)
    bad = [x for x in names if x not in roth_svc.MODES]
    if bad:
        return jsonify(error=f"unknown modes: {bad}"), 400
    return jsonify(
        planner.roth_plan(
            get_profile(),
            names,
            detail=request.args.get("detail", "1") != "0",
            retire_age=request.args.get("retire_age", type=float),
            bracket_rate=request.args.get("bracket_rate", 0.12, type=float),
            until_age=request.args.get("until_age", type=float),
        )
    )


SAVINGS_FLOATS = (
    "salary", "annual_saving", "magi", "annual_spend", "match_rate", "match_cap_pct", "employer_contrib",
    "real_return", "withdrawal_rate", "part_time_income", "pretax_ira_balance",
)  # fmt: skip
SAVINGS_FLAGS = ("hsa_eligible", "hsa_family", "prefer_roth_401k", "mega_backdoor", "not_covered_by_plan", "plan_allows_after_tax", "plan_allows_in_service")


@bp.get("/planner/savings")
def savings():
    args: dict = {k: request.args.get(k, type=float) for k in SAVINGS_FLOATS if request.args.get(k) is not None}
    args.update({k: request.args.get(k) in ("1", "true") for k in SAVINGS_FLAGS if k in request.args})
    if request.args.get("year", type=int):
        args["year"] = request.args.get("year", type=int)
    return jsonify(planner.savings_plan(get_profile(), args))


@bp.get("/planner/strategies")
def strategies():
    names = [x for x in request.args.get("policies", "").split(",") if x] or list(ws_svc.POLICIES)
    bad = [x for x in names if x not in ws_svc.POLICIES]
    if bad:
        return jsonify(error=f"unknown policies: {bad}"), 400
    p = {k: request.args.get(k, type=float) for k in ("portfolio", "retire_age", "end_age", "mu", "sigma") if request.args.get(k) is not None}
    p.update({k: request.args.get(k, type=int) for k in ("n_sims", "seed") if request.args.get(k) is not None})
    p["detail"] = request.args.get("detail", "1") != "0"
    return jsonify(planner.strategy_plan(get_profile(), tuple(names), p))


@bp.get("/planner/stress")
def stress():
    policy = request.args.get("policy", "fixed_real")
    if policy not in ws_svc.POLICIES:
        return jsonify(error=f"unknown policy: {policy}"), 400
    p = {
        k: request.args.get(k, type=float) for k in ("portfolio", "retire_age", "end_age", "spend", "equity", "mu", "sigma") if request.args.get(k) is not None
    }
    p.update({k: request.args.get(k, type=int) for k in ("n_sims", "seed") if request.args.get(k) is not None})
    p["policy"] = policy
    if request.args.get("starts"):
        p["starts"] = [int(x) for x in request.args["starts"].split(",") if x.strip().isdigit()]
    return jsonify(planner.stress_plan(get_profile(), p))


@bp.get("/planner/social-security")
def social_security():
    return jsonify(
        planner.social_security_plan(
            get_profile(),
            haircut=request.args.get("haircut", 0, type=float),
            haircut_year=request.args.get("haircut_year", type=int),
            real_rate=request.args.get("real_rate", 0.02, type=float),
            modal=request.args.get("modal_age", 88, type=float),
        )
    )


@bp.get("/planner/spending")
def spending():
    smile = request.args.get("smile")
    return jsonify(
        planner.spending_plan(
            get_profile(),
            nominal=request.args.get("nominal") in ("1", "true"),
            base_annual=request.args.get("base_annual", type=float),
            smile=None if smile is None else smile in ("1", "true"),
        )
    )


@bp.get("/planner/healthcare")
def healthcare():
    a = request.args
    p = {k: a.get(k, type=float) for k in ("magi", "ltc_annual", "ltc_years", "hsa_balance", "hsa_medical_spend") if a.get(k) is not None}
    p |= {k: a.get(k, type=int) for k in ("year", "people") if a.get(k) is not None}
    if a.get("status"):
        p["status"] = a["status"].upper()
    return jsonify(planner.healthcare_plan(get_profile(), p))


@bp.get("/planner/income-streams")
def income_streams_route():
    return jsonify(planner.income_streams_plan(get_profile()))


@bp.get("/planner/assumptions")
def assumptions_route():
    return jsonify(planner.assumptions_view())


@bp.put("/planner/assumptions")
def assumptions_save():
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("overrides"), dict):
        return jsonify({"error": "overrides object required"}), 400
    try:
        return jsonify(planner.save_assumptions(body["overrides"]))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.get("/planner/fee-drag")
def fee_drag_route():
    a = request.args
    return jsonify(
        assumptions_svc.fee_drag(
            a.get("balance", 0.0, type=float),
            a.get("contribution", 0.0, type=float),
            min(max(a.get("years", 30, type=int), 1), 70),
            a.get("gross_return", 0.07, type=float),
            a.get("fee", assumptions_svc.BY_KEY["fee.expense_ratio"]["default"], type=float),
        )
    )


@bp.get("/planner/health")
def health_route():
    return jsonify(planner.plan_health(get_profile(), n_sims=min(max(request.args.get("sims", 1000, type=int), 200), 10000)))


@bp.post("/planner/health/snapshot")
def health_snapshot():
    return jsonify(planner.plan_health(get_profile(), save=True))


@bp.get("/planner/survivor")
def survivor_route():
    a = request.args
    keys = ("annual_spend", "pretax_draw", "other_ordinary", "spend_ratio", "net_worth", "income", "liquid_assets", "existing_life", "group_disability_monthly")
    p = {k: a.get(k, type=float) for k in keys if a.get(k) is not None}
    if a.get("deceased"):
        p["deceased"] = a["deceased"].upper()
    return jsonify(planner.survivor_plan(get_profile(), p))


@bp.get("/planner/real-estate")
def real_estate():
    a = request.args
    keys = (
        "home_value", "appreciation", "years", "new_home_price", "cost_basis", "selling_cost_pct", "other_income",
        "annual_spend", "current_col_index", "target_col_index",
    )  # fmt: skip
    p = {k: a.get(k, type=float) for k in keys if a.get(k) is not None}
    for k in ("status", "target_state"):
        if a.get(k):
            p[k] = a[k].upper()
    return jsonify(planner.real_estate_plan(get_profile(), p))


@bp.get("/planner/scenarios")
def scenario_list():
    return jsonify({"saved": [x.to_dict() for x in db.session().query(Scenario).order_by(Scenario.id)], "presets": scen_svc.presets_public()})


@bp.post("/planner/scenarios")
def scenario_create():
    data = ScenarioIn.model_validate(request.get_json(force=True))
    s = db.session()
    x = Scenario(**data.model_dump())
    s.add(x)
    s.commit()
    return jsonify(x.to_dict()), 201


@bp.delete("/planner/scenarios/<int:sid>")
def scenario_delete(sid):
    s = db.session()
    x = s.get(Scenario, sid)
    if x is None:
        return jsonify(error="not found"), 404
    s.delete(x)
    s.commit()
    return "", 204


@bp.get("/planner/scenarios/compare")
def scenario_compare():
    p = get_profile()
    ids = [int(i) for i in request.args.get("ids", "").split(",") if i.strip().isdigit()]
    names = [n for n in request.args.get("presets", "").split(",") if n]
    bad = [n for n in names if n not in scen_svc.PRESETS]
    if bad:
        return jsonify(error=f"unknown presets: {bad}"), 400
    n = request.args.get("n", type=float)
    saved = list(db.session().query(Scenario).filter(Scenario.id.in_(ids))) if ids else []
    return jsonify(planner.scenario_compare(p, saved, [scen_svc.preset(x, p, n) for x in names], request.args.get("sims", 1500, type=int)))


@bp.get("/planner/tornado")
def tornado():
    return jsonify(planner.scenario_tornado(get_profile(), request.args.get("sims", 800, type=int)))


@bp.get("/planner/solve")
def solve():
    try:
        return jsonify(
            planner.scenario_solve(
                get_profile(), request.args.get("kind", "max_spend"), request.args.get("target", type=float), request.args.get("sims", 800, type=int)
            )
        )
    except ValueError as e:
        return jsonify(error=str(e)), 400


@bp.get("/planner/event-templates")
def event_templates():
    return jsonify({n: spending_svc.event_from_template(n, date.today().year + 1)[0] for n in spending_svc.template_names()})


@bp.post("/planner/events/from-template")
def event_from_template():
    body = request.get_json(force=True)
    name = body.get("template")
    if name not in spending_svc.template_names():
        return jsonify(error=f"unknown template: {name}"), 400
    rows = spending_svc.event_from_template(name, int(body.get("start_year") or date.today().year + 1), body.get("amount"), body.get("owner", "JOINT"))
    s = db.session()
    made = []
    for row in rows:
        e = PlannedEvent(**PlannedEventIn.model_validate(row).model_dump())
        s.add(e)
        made.append(e)
    s.commit()
    return jsonify([e.to_dict() for e in made]), 201


@bp.get("/planner/events")
def event_list():
    return jsonify([e.to_dict() for e in db.session().query(PlannedEvent).order_by(PlannedEvent.start_year, PlannedEvent.id)])


@bp.post("/planner/events")
def event_create():
    data = PlannedEventIn.model_validate(request.get_json(force=True))
    s = db.session()
    e = PlannedEvent(**data.model_dump())
    s.add(e)
    s.commit()
    return jsonify(e.to_dict()), 201


@bp.put("/planner/events/<int:eid>")
def event_update(eid):
    data = PlannedEventIn.model_validate(request.get_json(force=True))
    s = db.session()
    e = s.get(PlannedEvent, eid)
    if e is None:
        return jsonify(error="not found"), 404
    for k, v in data.model_dump().items():
        setattr(e, k, v)
    s.commit()
    return jsonify(e.to_dict())


@bp.delete("/planner/events/<int:eid>")
def event_delete(eid):
    s = db.session()
    e = s.get(PlannedEvent, eid)
    if e:
        s.delete(e)
        s.commit()
    return "", 204


@bp.get("/planner/barbell")
def barbell():
    return jsonify(planner.barbell_summary(db.session()))


@bp.get("/planner/cash")
def cash():
    s = db.session()
    p = get_profile()
    try:
        market, notes = market_data.market_inputs(current_app.config["FRED_API_KEY"])
    except Exception:
        current_app.logger.exception("cash plan: market data unavailable")
        return jsonify(error="Market data unavailable"), 503
    mmf = p.current_money_market_yield if p.money_market_yield_override else max(market.tbill_3m - 0.0015, 0)
    rec = planner.cash_recommendation(s, p, mmf, market)
    rec["market"] = market.__dict__
    rec["notes"] = notes
    rec["satellite_allocation"] = planner.allocate_surplus(rec["deploy_now"], p.risk_appetite)
    return jsonify(rec)


@bp.get("/planner/cash/plan")
def cash_plan_route():
    """Ladder, T-bill vs money-market tax comparison, emergency + bridge reserves and DCA schedule (deterministic)."""
    s = db.session()
    p = get_profile()
    try:
        market, notes = market_data.market_inputs(current_app.config["FRED_API_KEY"])
    except Exception as e:
        return jsonify(error=f"Market data unavailable: {e}"), 503
    mmf = p.current_money_market_yield if p.money_market_yield_override else max(market.tbill_3m - 0.0015, 0)
    a = request.args
    opts: dict = {}
    for k in ("ladder_amount", "cd_yield", "ibond_rate", "mmf_treasury_share"):
        if a.get(k) is not None:
            opts[k] = a.get(k, type=float)
    if a.get("rungs"):
        try:
            opts["rungs"] = [int(x) for x in a["rungs"].split(",") if x]
        except ValueError:
            return jsonify(error="rungs must be comma-separated months"), 400
        if not opts["rungs"] or any(m < 1 or m > 120 for m in opts["rungs"]):
            return jsonify(error="rungs must be 1-120 months"), 400
    out = cash_plan.build(s, p, market, mmf, opts)
    out["market_notes"] = notes
    out["dca_active"] = p.dca_plan or None
    return jsonify(out)


@bp.post("/planner/cash/dca")
def cash_dca_set():
    """Save a DCA schedule; the daily job sends one reminder per tranche when it falls due."""
    body = request.get_json(silent=True) or {}
    try:
        amount, tranches = float(body["amount"]), int(body["tranches"])
        start = date.fromisoformat(body.get("start") or date.today().isoformat())
    except (KeyError, TypeError, ValueError):
        return jsonify(error="amount, tranches (and optional ISO start) required"), 400
    if amount <= 0 or not 1 <= tranches <= 24:
        return jsonify(error="amount must be positive and tranches 1-24"), 400
    p = get_profile()
    p.dca_plan = {
        "amount": amount,
        "tranches": tranches,
        "schedule": ladder_svc.dca_schedule(amount, tranches, start, body.get("interval_days")),
        "notified": [],
    }
    db.session().commit()
    return jsonify(p.dca_plan)


@bp.delete("/planner/cash/dca")
def cash_dca_clear():
    get_profile().dca_plan = {}
    db.session().commit()
    return "", 204


@bp.get("/planner/cash/backtest")
def cash_backtest_route():
    return jsonify(cash_backtest.run())


@bp.get("/planner/menu-grade/<int:aid>")
def menu_grade(aid):
    s = db.session()
    a = s.get(Account, aid)
    if a is None:
        return jsonify(error="not found"), 404
    menu = [
        {c: getattr(m, c) for c in ("ticker_or_cusip", "fund_name", "asset_class", "expense_ratio")} for m in s.query(AllowedPlanMenu).filter_by(account_id=aid)
    ]
    return jsonify(planner.grade_menu(menu, [holding_dict(h) for h in a.holdings]))


@bp.get("/planner/debt")
def debt():
    p = get_profile()
    mmf = p.current_money_market_yield
    expected = quant_engine.ASSET_ASSUMPTIONS["US_EQUITY"][0]
    return jsonify(liab_svc.debt_summary(p, db.session().query(Liability).order_by(Liability.id).all(), mmf, expected))
