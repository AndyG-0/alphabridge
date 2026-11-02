"""Read-only tools the chat agent can call. Every number comes from deterministic code or cached market data."""

import json
from datetime import date
from types import SimpleNamespace

from flask import current_app

import db
from models import (
    Account,
    AllowedPlanMenu,
    CoverageOption,
    Holding,
    IngestionLog,
    Liability,
    NetWorthSnapshot,
    NotificationConfig,
    Pension,
    PlannedEvent,
    ResearchReport,
    ScreenerResult,
    TaxLot,
)
from routes._helpers import get_profile
from services import (
    actions,
    cash_backtest,
    cash_plan,
    chart_data,
    early_access,
    household,
    hsa,
    market_data,
    networth,
    onboarding,
    performance,
    planner,
    rebalance,
    research_watch,
    risk,
    rmd,
    roth,
    scenarios,
    spending,
    state_rules,
    tax_lots,
    transactions,
    withdrawals,
    xray,
)
from services import pension as pension_svc
from services import quant_engine as qe
from services import research_pipeline as rp
from services import withdrawal_strategies as ws

MAX_RESULT_CHARS = 12000


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


NUM = {"type": "number"}
TOOLS = [
    ("get_profile", "Household profile: ages, income, expenses, savings, spouse details, tax rate, risk settings.", _obj({})),
    ("get_accounts_and_holdings", "All accounts (owner, tax bucket, bucket) with their holdings and values.", _obj({})),
    ("get_allocation", "Net worth by bucket (safe_core / satellite / dry_powder), asset-class weights and sector exposure.", _obj({})),
    (
        "run_fire_scenario",
        "Run the 5,000-path Monte Carlo early-retirement simulation, optionally overriding profile inputs to test a what-if. "
        "Returns success rate, bridge-phase success, bridge capital need vs projected, earliest viable retirement age.",
        _obj(
            {
                "retire_age": NUM,
                "spouse_retire_age": NUM,
                "monthly_expenses_retirement": NUM,
                "monthly_contribution": NUM,
                "social_security_monthly": NUM,
                "spouse_social_security_monthly": NUM,
                "ss_claim_age": NUM,
                "spouse_ss_claim_age": NUM,
                "aca_benchmark_premium_monthly": NUM,
                "home_value": NUM,
                "ltc_years": NUM,
                "guardrails": {"type": "boolean"},
                "add_purchase_amount": NUM,
                "add_purchase_year": {"type": "integer"},
                "rule_of_55": {"type": "boolean"},
                "monthly_expenses_current": NUM,
                "target_success_rate": NUM,
                "health_oop_annual": NUM,
                "medicare_monthly_per_person": NUM,
                "ltc_annual": NUM,
                "ltc_start_age": NUM,
                "state": {"type": "string", "description": "Two-letter state code (Medicaid rules)"},
                "meets_community_engagement": {"type": "boolean"},
            }
        ),
    ),
    ("get_planned_events", "Planned big purchases (cars, roof), lump-sum inflows (inheritance, home sale) and pensions.", _obj({})),
    ("get_cash_signal", "Cash-vs-market deployment score (0-100), signal HOLD_MMF/DCA/AGGRESSIVE_BUY, dollars to deploy and why.", _obj({})),
    ("get_market_snapshot", "Macro inputs: 3m T-bill, 10Y yield, CPI, VIX, S&P 500 P/E and distance from 200-day average.", _obj({})),
    ("get_stock_snapshot", "Price, RSI14, distance from 200-day average and fundamentals for one ticker.", _obj({"symbol": {"type": "string"}}, ["symbol"])),
    (
        "what_if_add_position",
        "Effect of putting `amount` dollars into `symbol`: beta, sector concentration and warnings.",
        _obj({"symbol": {"type": "string"}, "amount": NUM}, ["symbol", "amount"]),
    ),
    ("get_research_reports", "Latest saved AI equity research reports (action, grades, fit notes).", _obj({"limit": {"type": "integer"}})),
    (
        "get_liabilities",
        "Debts (mortgage, auto, cards, student, HELOC) with payoff timelines, debt-to-income and a pay-down-vs-invest "
        "recommendation per debt. Profile expenses exclude debt payments.",
        _obj({}),
    ),
    (
        "get_coverage_options",
        "User-defined health-coverage alternatives to ACA / flat Medicare (employer retiree plans, Medicare Advantage, drug add-ons) with prices by year, "
        "eligibility ages and which option each person has chosen for the plan.",
        _obj({}),
    ),
    ("get_pensions", "Employer cash-balance pensions with projected balance and monthly annuity at the start age.", _obj({})),
    (
        "get_withdrawal_plan",
        "Which accounts to draw each retirement year: compares taxable-first, proportional, bracket-fill and ACA-MAGI-target strategies "
        "on lifetime tax + ACA premiums, shortfalls and ending after-tax wealth, using the federal/state tax engine and the plan year's ACA schedule.",
        _obj({"retire_age": NUM, "strategies": {"type": "array", "items": {"type": "string"}}}),
    ),
    (
        "get_social_security_plan",
        "Social Security claiming analysis: monthly benefit at each claim age 62-70, break-even ages, and the longevity-weighted household NPV "
        "of every claim-age pair including spousal and survivor benefits, with an optional benefit-cut haircut.",
        _obj({"haircut": NUM, "haircut_year": {"type": "integer"}, "real_rate": NUM}),
    ),
    (
        "get_withdrawal_strategies",
        "Compares retirement spending policies (fixed real, % of portfolio, Guyton-Klinger, ratcheting, floor-and-ceiling, VPW, cash bucket) under "
        "seeded Monte Carlo: the maximum initial spend at 90% and 95% success, spend bands (p10/p50/p90 by year) and worst-year spend, in real dollars.",
        _obj({"portfolio": NUM, "retire_age": NUM, "end_age": NUM, "policies": {"type": "array", "items": {"type": "string"}}}),
    ),
    (
        "get_stress_tests",
        "Sequence-of-returns stress tests for the retirement plan: replays of 1929/1966/1973/2000/2008 starts, every rolling historical window, "
        "block-bootstrap, fat-tail and regime-switching simulations, success versus first-five-year return, and a cash-bucket mitigation test. "
        "Each method is labelled with its assumptions; real dollars.",
        _obj({"portfolio": NUM, "spend": NUM, "equity": NUM, "retire_age": NUM, "end_age": NUM, "policy": {"type": "string"}}),
    ),
    (
        "get_spending_projection",
        "Retirement base spending by year and category (housing, food, transport, education, discretionary, other) under the user's spending model: "
        "optional go-go/slow-go/no-go smile and per-category inflation above general. Real (today's dollars) or nominal. Health care is separate.",
        _obj({"nominal": {"type": "boolean"}, "smile": {"type": "boolean"}, "base_annual": NUM}),
    ),
    (
        "get_healthcare_costs",
        "Medicare cost (Part B, Part D, Medigap plus IRMAA surcharge at a given MAGI), pre-65 ACA net premiums by age, HSA run-out, and "
        "long-term-care expected-value vs stress cost. Today's dollars; the plan applies health inflation separately.",
        _obj({"magi": NUM, "status": {"type": "string"}, "people": NUM, "year": NUM, "ltc_annual": NUM, "ltc_years": NUM, "hsa_balance": NUM}),
    ),
    (
        "get_income_streams",
        "Taxed non-portfolio income events the user planned (annuity/SPIA, part-time work, rental, RSU/ESPP/NSO, inheritance, business sale): "
        "per-year gross cash, taxable ordinary/capital-gain income, incremental tax and after-tax cash.",
        _obj({}),
    ),
    (
        "get_assumptions",
        "Every model assumption (returns, volatility, inflation, correlations, fees) with its default, current value, "
        "whether the user changed it, and its source.",
        _obj({}),
    ),
    (
        "get_fee_drag",
        "Dollar and percent cost of a fund fee over time on a balance plus yearly contributions. Pass balance, contribution, years, gross_return, fee.",
        _obj({"balance": NUM, "contribution": NUM, "years": NUM, "gross_return": NUM, "fee": NUM}),
    ),
    (
        "get_xray",
        "Portfolio X-Ray: look-through exposure by asset class, sector, region and market-cap tier, fund overlap, top underlying names, "
        "employer-stock concentration and which funds lack look-through data (coverage).",
        _obj({}),
    ),
    (
        "get_plan_health",
        "0-100 plan health score with the parts that make it up, and what changed in the results and assumptions since the last saved run.",
        _obj({}),
    ),
    (
        "get_survivor_plan",
        "If one spouse dies: Social Security the survivor keeps, single-filer tax on the same income (widow's penalty), estate-tax exposure vs the "
        "federal exclusion, a beneficiary/re-titling checklist and term-life and disability gaps. Optional: deceased (SELF|SPOUSE), annual_spend, net_worth.",
        _obj({"deceased": {"type": "string"}, "annual_spend": NUM, "net_worth": NUM, "income": NUM, "existing_life": NUM, "group_disability_monthly": NUM}),
    ),
    (
        "get_real_estate_plan",
        "Home value/mortgage/equity by year, pay-down-vs-invest advice per debt, and optional what-ifs: downsizing (selling costs, section 121 "
        "exclusion, tax, cash freed, upkeep change; pass new_home_price) and relocation (cost-of-living ratio, state-tax change; pass target_col_index).",
        _obj({"home_value": NUM, "appreciation": NUM, "new_home_price": NUM, "cost_basis": NUM, "target_col_index": NUM, "target_state": {"type": "string"}}),
    ),
    (
        "list_scenarios",
        "Saved what-if scenarios (name, profile overrides, first-year market shock) and the built-in presets (retire at N, spend +/-10%, -30% crash, "
        "Social Security cut, spouse death, job loss).",
        _obj({}),
    ),
    (
        "compare_scenarios",
        "Run the baseline plus saved scenario ids and/or preset names; success, bridge success and ending wealth side by side with differences.",
        _obj({"ids": {"type": "array", "items": NUM}, "presets": {"type": "array", "items": {"type": "string"}}, "n": NUM}),
    ),
    (
        "get_sensitivity_tornado",
        "Which inputs move the plan's success rate most (retire age, spending, savings, Social Security, health inflation, taxes, crash), ranked by swing.",
        _obj({}),
    ),
    (
        "solve_plan",
        "Reverse solver for a target success rate: kind=max_spend (largest monthly spend), required_savings (smallest monthly savings) or earliest_age.",
        _obj({"kind": {"type": "string", "enum": ["max_spend", "required_savings", "earliest_age"]}, "target": NUM}),
    ),
    (
        "get_event_templates",
        "Life-event templates the user can add to the plan (college, wedding, home purchase, car, downsizing) with placeholder amounts in today's dollars.",
        _obj({}),
    ),
    (
        "get_savings_plan",
        "Contribution limits for the year (401k, catch-up, 60-63 super catch-up, IRA/Roth phase-outs, HSA), the savings waterfall "
        "(match -> HSA -> Roth/IRA -> 401k -> taxable), backdoor/mega-backdoor checklist, and FI / Lean / Fat / Barista / Coast numbers "
        "with years-to-FI sensitivity.",
        _obj(
            {
                "salary": NUM,
                "annual_saving": NUM,
                "annual_spend": NUM,
                "match_rate": NUM,
                "match_cap_pct": NUM,
                "real_return": NUM,
                "withdrawal_rate": NUM,
                "part_time_income": NUM,
                "hsa_eligible": {"type": "boolean"},
                "hsa_family": {"type": "boolean"},
                "mega_backdoor": {"type": "boolean"},
            }
        ),
    ),
    (
        "get_roth_conversion_plan",
        "Roth conversion ladder by year for three modes (fill a tax bracket, stay under the ACA MAGI target, stay under the first IRMAA tier) versus no "
        "conversions: conversion amounts, 5-year seasoning ledger, conversion tax, lifetime tax + premiums, ending after-tax wealth, "
        "bridge coverage and RMD reduction.",
        _obj({"retire_age": NUM, "bracket_rate": NUM, "until_age": NUM, "modes": {"type": "array", "items": {"type": "string"}}}),
    ),
    (
        "get_rmd_projection",
        "Required minimum distributions by year for each person's pre-tax accounts (SECURE 2.0 start age, Uniform Lifetime Table), optional annual QCD, "
        "and what the peak RMD does to the household's tax bracket and IRMAA tier.",
        _obj({"qcd_annual": NUM, "real_return": NUM}),
    ),
    (
        "get_inherited_rmd",
        "Distribution schedule for an inherited retirement account (10-year rule, annual RMDs when the owner was past their required beginning date, "
        "or life-expectancy stretch for eligible designated beneficiaries).",
        _obj(
            {
                "balance": NUM,
                "beneficiary_age": {"type": "integer"},
                "death_year": {"type": "integer"},
                "owner_died_on_or_after_rbd": {"type": "boolean"},
                "eligible_designated": {"type": "boolean"},
            },
            ["balance", "beneficiary_age", "death_year"],
        ),
    ),
    (
        "get_early_access",
        "Per pre-tax account: when money is penalty-free (59.5, Rule of 55, SEPP), the 10% penalty exposure before then, "
        "rollover advice, and the list of penalty exceptions.",
        _obj({}),
    ),
    (
        "get_sepp_payment",
        "72(t) SEPP annual payment for a balance, start age and interest rate (method amortization|annuitization|rmd).",
        _obj(
            {"balance": NUM, "age": {"type": "integer"}, "rate": NUM, "method": {"type": "string"}, "table": {"type": "string"}, "mid_term_rate": NUM},
            ["balance", "age"],
        ),
    ),
    (
        "get_roth_withdrawal_order",
        "Which Roth dollars a withdrawal uses (contributions, then conversions oldest first, then earnings) and the tax/10% penalty on each layer.",
        _obj(
            {
                "withdraw": NUM,
                "age": NUM,
                "year": {"type": "integer"},
                "roth_open_year": {"type": "integer"},
                "contributions": NUM,
                "earnings": NUM,
                "conversions": {"type": "array", "items": _obj({"year": {"type": "integer"}, "amount": NUM}, ["year", "amount"])},
            },
            ["withdraw", "age", "year", "roth_open_year"],
        ),
    ),
    (
        "get_state_health_rules",
        "Medicaid/ACA rules for the profile's state plus the 2027+ community-engagement requirement.",
        _obj({"state": {"type": "string"}}),
    ),
    (
        "get_hsa_limits",
        "HSA annual contribution limit for a year, coverage type and age (includes the age-55 catch-up).",
        _obj({"year": {"type": "integer"}, "family": {"type": "boolean"}, "age": NUM}),
    ),
    (
        "get_tax_estimate",
        "Deterministic federal + state tax for ordinary income, qualified gains and Social Security (defaults from the profile): "
        "brackets, LTCG stacking, NIIT, taxable Social Security, IRMAA tier.",
        _obj(
            {"ordinary": NUM, "qualified": NUM, "social_security": NUM, "year": {"type": "integer"}, "status": {"type": "string"}, "state": {"type": "string"}}
        ),
    ),
    ("get_household_timeline", "Dated milestones for both people: retirement, Social Security, Medicare, debt payoffs, planned events.", _obj({})),
    ("get_debt_payoff_schedule", "When each debt is paid off, with both people's ages, and whether it is gone before retirement.", _obj({})),
    (
        "get_plan_menu",
        "Entered 401(k) plan-menu funds (ticker, name, asset class, expense ratio) for one account.",
        _obj({"account_id": {"type": "integer"}}, ["account_id"]),
    ),
    (
        "get_spending_actuals",
        "Measured monthly spending from imported transactions vs the plan assumption: average, by category, lifestyle-creep flag, uncategorized count.",
        _obj({"months": {"type": "integer"}}),
    ),
    (
        "get_action_items",
        "The prioritized to-do feed (employer match, Roth conversion, rebalance, tax-loss harvest, stale statements, year-end checklist), "
        "each with a 0-100 priority, dollar impact and where to act. Set include_hidden to also see snoozed and done items.",
        _obj({"include_hidden": {"type": "boolean"}}),
    ),
    (
        "get_chart_data",
        "Numbers behind the charts: kind='brackets' (ordinary tax brackets filled by a MAGI, with marginal rate; optional magi, year) or "
        "kind='cashflow' (this year's income split into taxes, spending, debt payments, savings and leftover).",
        _obj({"kind": {"type": "string", "enum": ["brackets", "cashflow"]}, "magi": {"type": "number"}, "year": {"type": "integer"}}, ["kind"]),
    ),
    (
        "get_onboarding_status",
        "Setup progress: which wizard steps are done (household, accounts, upload, goals, first plan) and a 0-100 data-completeness score with, "
        "for each missing input, what it would make more accurate. Use to explain why a result may be imprecise.",
        _obj({}),
    ),
    ("get_ingestion_log", "Recent file imports: filename, parser, rows, status (OK/ERROR/UNDONE), message.", _obj({"limit": {"type": "integer"}})),
    (
        "get_data_gaps",
        "Deterministic checklist of missing or suspicious inputs (zero income/expenses/Social Security, no spouse data, accounts without "
        "holdings or plan menus, unmapped holdings, no pension/debts entered, no LLM or alert channel). Call before saying data is missing.",
        _obj({}),
    ),
    ("get_screener_results", "Latest quant screener output (ranked candidates and metrics).", _obj({"limit": {"type": "integer"}})),
    ("get_sector_overview", "Sector relative-strength ranking used by the macro overlay.", _obj({})),
    ("get_notification_status", "Whether Discord/SMTP alert channels are configured (never secrets) and background job status.", _obj({})),
    ("get_net_worth_history", "Net-worth snapshots over time.", _obj({"limit": {"type": "integer"}})),
    (
        "get_net_worth_summary",
        "Net-worth series with asset/liability breakdown, milestones reached and next, and monthly plan-vs-actual drift "
        "(deterministic projection from the first snapshot).",
        _obj({}),
    ),
    (
        "get_performance",
        "Portfolio time-weighted and money-weighted return, comparison with SPY and the target allocation, fee drag from expense ratios, "
        "and a monthly dividend/interest income calendar (deterministic).",
        _obj({"assume_contributions": {"type": "boolean"}}),
    ),
    (
        "get_rebalance_plan",
        "Drift from the target allocation, a self-funding trade list that respects 401(k) menus and minimizes realized gains in taxable, "
        "estimated tax on those gains, and asset-location suggestions (deterministic).",
        _obj({"threshold": {"type": "number"}}),
    ),
    (
        "get_cash_plan",
        "Cash engine details: Treasury/CD ladder, T-bill vs money-market after-tax comparison for the user's state, I-bond cap, emergency fund "
        "and first-years-of-retirement bridge reserve from the withdrawal simulator, and the DCA schedule (deterministic).",
        _obj({"ladder_amount": {"type": "number"}, "cd_yield": {"type": "number"}, "ibond_rate": {"type": "number"}}),
    ),
    (
        "get_cash_backtest",
        "Historical backtest (annual Damodaran data) of the cash-deployment rule vs buy-and-hold, naive DCA and T-bills (deterministic).",
        _obj({}),
    ),
    (
        "get_dcf_sensitivity",
        "Per-share DCF value grid over growth x discount rate for a symbol (deterministic); use the range, not one number.",
        _obj({"symbol": {"type": "string"}}, ["symbol"]),
    ),
    (
        "get_insider_activity",
        "Open-market insider buying/selling from recent Form 4 filings over the last 90 days, net value and a BUYING/SELLING/NEUTRAL signal (deterministic).",
        _obj({"symbol": {"type": "string"}}, ["symbol"]),
    ),
    (
        "get_watchlist",
        "Watchlist with price, base DCF value and any valuation alerts that are firing (deterministic).",
        _obj({}),
    ),
    (
        "get_theses",
        "Investment theses with their invalidation criteria checked against current data; 'broken' lists the criteria that have triggered.",
        _obj({}),
    ),
    (
        "get_risk_report",
        "Portfolio risk from price history at today's weights: volatility, max drawdown, 1-day VaR/CVaR, beta, correlations, "
        "each position's share of risk, plus historical stress tests (2000-02, 2008, 2022, 1973-74) applied to actual holdings (deterministic).",
        _obj({}),
    ),
    (
        "get_tax_lot_report",
        "Lot-level tax report: tax-loss harvest candidates with estimated savings and wash-sale conflicts (any household account), "
        "0% long-term gain-harvesting headroom, and short-term lots about to turn long-term (deterministic, federal only).",
        _obj({}),
    ),
    (
        "suggest_lot_sale",
        "Which specific tax lots to sell to raise a dollar amount of one symbol with the least tax (losses first), with estimated gain and tax.",
        _obj({"symbol": {"type": "string"}, "amount": {"type": "number"}, "account_id": {"type": "integer"}}, ["symbol", "amount"]),
    ),
    (
        "grade_401k_menu",
        "Grade an account's plan menu by expense ratio and suggest cheaper swaps (needs menu entries).",
        _obj({"account_id": {"type": "integer"}}, ["account_id"]),
    ),
]
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": p}} for n, d, p in TOOLS]


def _profile_dict(p) -> dict:
    return p.to_dict()


def _accounts() -> list[dict]:
    from routes.portfolio_routes import account_dict

    return [account_dict(a) for a in db.session().query(Account).order_by(Account.id)]


def _fire(a: dict) -> dict:
    p = _profile_dict(get_profile())
    map_ = {
        "retire_age": "target_retirement_age",
        "spouse_retire_age": "spouse_target_retirement_age",
        "monthly_expenses_retirement": "monthly_expenses_retirement",
        "monthly_contribution": "monthly_contribution",
        "social_security_monthly": "social_security_monthly",
        "spouse_social_security_monthly": "spouse_social_security_monthly",
        "ss_claim_age": "ss_claim_age",
        "spouse_ss_claim_age": "spouse_ss_claim_age",
        "aca_benchmark_premium_monthly": "aca_benchmark_premium_monthly",
        "home_value": "home_value",
        "ltc_years": "ltc_years",
        "monthly_expenses_current": "monthly_expenses_current",
        "target_success_rate": "target_success_rate",
        "health_oop_annual": "health_oop_annual",
        "medicare_monthly_per_person": "medicare_monthly_per_person",
        "ltc_annual": "ltc_annual",
        "ltc_start_age": "ltc_start_age",
    }
    for k, col in map_.items():
        if a.get(k) is not None:
            p[col] = float(a[k])
    if a.get("state"):
        p["state"] = str(a["state"]).upper()[:2]
    if a.get("meets_community_engagement") is not None:
        p["meets_community_engagement"] = bool(a["meets_community_engagement"])
    events = db.session().query(PlannedEvent).all()
    if a.get("add_purchase_amount") and a.get("add_purchase_year"):
        events = [
            *events,
            SimpleNamespace(
                name="What-if purchase",
                kind="PURCHASE",
                amount=float(a["add_purchase_amount"]),
                start_year=int(a["add_purchase_year"]),
                repeat_every_years=0,
                repeat_until_year=None,
                owner="JOINT",
                financed=False,
                down_payment=0.0,
                loan_apr=0.0,
                loan_term_months=60,
                is_home_sale=False,
            ),
        ]
    res = planner.run_fire(SimpleNamespace(**p), n_sims=5000, rule_of_55=bool(a.get("rule_of_55")), events=events, guardrails=a.get("guardrails"))
    path = res.pop("median_path_real", [])
    res.pop("path", None)
    res["median_net_worth_by_age_real"] = [(round(x), round(v)) for x, v in path if round(x) % 5 == 0]
    health = res.pop("health", [])
    res["health_care_first_years"] = [
        {
            k: (round(v) if isinstance(v, float) else v)
            for k, v in h.items()
            if k in ("year", "coverage", "aca_net", "aca_credit", "medicare", "total", "over_cliff", "magi_est")
        }
        for h in health
        if h["coverage"] != "EMPLOYER"
    ][:6]
    res["timeline"] = [{k: m[k] for k in ("year", "ages", "label")} for m in res.get("timeline", [])][:25]
    res["assumptions_used"] = {k: p[c] for k, c in map_.items()}
    return res


def _events(_a: dict) -> list[dict]:
    return [e.to_dict() for e in db.session().query(PlannedEvent).order_by(PlannedEvent.start_year)]


def _cash() -> dict:
    p = get_profile()
    s = db.session()
    market, notes = market_data.market_inputs(current_app.config["FRED_API_KEY"])
    mmf = p.current_money_market_yield if p.money_market_yield_override else max(market.tbill_3m - 0.0015, 0)
    rec = planner.cash_recommendation(s, p, mmf, market)
    return {**rec, "notes": notes}


def _stock(a: dict) -> dict:
    sym = a["symbol"].upper()
    closes = market_data.get_closes(sym, "2y")
    import numpy as np

    arr = np.array(closes) if closes else None
    out = {"symbol": sym, "price": closes[-1] if closes else None}
    if arr is not None and len(arr) > 20:
        out["rsi14"] = qe.rsi(arr)
        out["sma200_distance"] = qe.sma_distance(arr)
        out["max_drawdown_2y"] = qe.max_drawdown(arr)
    out["fundamentals"] = rp._safe_fund(sym)
    return out


def _reports(a: dict) -> list[dict]:
    rows = db.session().query(ResearchReport).order_by(ResearchReport.created_at.desc()).limit(min(int(a.get("limit") or 5), 15))
    return [
        {
            "symbol": r.symbol,
            "action": r.recommended_action,
            "quant_score": r.quant_score,
            "valuation": r.valuation_grade,
            "growth": r.growth_grade,
            "moat": r.moat_grade,
            "fit": r.portfolio_fit_notes,
            "bull": r.bull_case_md[:600],
            "bear": r.bear_case_md[:600],
            "created": r.created_at.isoformat(),
        }
        for r in rows
    ]


def _history(a: dict) -> list[dict]:
    rows = db.session().query(NetWorthSnapshot).order_by(NetWorthSnapshot.taken_at.desc()).limit(min(int(a.get("limit") or 12), 60))
    return [{"at": r.taken_at.isoformat(), "total": r.total} for r in rows][::-1]


def _liabilities() -> dict:
    from services import liabilities as liab_svc

    p = get_profile()
    return liab_svc.debt_summary(
        p, db.session().query(Liability).order_by(Liability.id).all(), p.current_money_market_yield, qe.ASSET_ASSUMPTIONS["US_EQUITY"][0]
    )


def _menu(a: dict) -> dict:
    s = db.session()
    acct = s.get(Account, int(a["account_id"]))
    if acct is None:
        return {"error": "account not found"}
    from routes.portfolio_routes import holding_dict

    menu = [
        {c: getattr(m, c) for c in ("ticker_or_cusip", "fund_name", "asset_class", "expense_ratio")}
        for m in s.query(AllowedPlanMenu).filter_by(account_id=acct.id)
    ]
    if not menu:
        return {"error": "no plan menu entered for this account, so fund swaps can't be graded"}
    return planner.grade_menu(menu, [holding_dict(h) for h in acct.holdings])


def _coverage_options() -> dict:
    s = db.session()
    opts = s.query(CoverageOption).order_by(CoverageOption.sort_order, CoverageOption.id).all()
    return {"options": [o.to_dict() for o in opts], "choice": get_profile().coverage_choice or {}}


def _pensions() -> list[dict]:
    profile = get_profile()
    out = []
    for p in db.session().query(Pension).order_by(Pension.owner):
        person = next((x for x in household.people(profile) if x.key == p.owner), None)
        out.append(p.to_dict() | {"projection": pension_svc.projection(p, person.age_now, person.retire_age) if person else None})
    return out


def _withdrawals(a: dict) -> dict:
    names = [x for x in (a.get("strategies") or []) if x in withdrawals.STRATEGIES] or list(withdrawals.STRATEGIES)
    return planner.withdrawal_plan(get_profile(), names, detail=False, retire_age=a.get("retire_age"))


def _social_security(a: dict) -> dict:
    return planner.social_security_plan(get_profile(), float(a.get("haircut") or 0), a.get("haircut_year"), float(a.get("real_rate") or 0.02))


def _strategies(a: dict) -> dict:
    names = [x for x in (a.get("policies") or []) if x in ws.POLICIES] or list(ws.POLICIES)
    p = {k: a[k] for k in ("portfolio", "retire_age", "end_age") if a.get(k) is not None}
    return planner.strategy_plan(get_profile(), tuple(names), p | {"detail": False, "n_sims": 1000})


def _stress(a: dict) -> dict:
    p = {k: a[k] for k in ("portfolio", "spend", "equity", "retire_age", "end_age") if a.get(k) is not None}
    pol = a.get("policy") if a.get("policy") in ws.POLICIES else "fixed_real"
    return planner.stress_plan(get_profile(), p | {"policy": pol, "n_sims": 1000})


def _spending(a: dict) -> dict:
    return planner.spending_plan(get_profile(), bool(a.get("nominal")), a.get("base_annual"), a.get("smile"))


def _healthcare(a: dict) -> dict:
    return planner.healthcare_plan(get_profile(), {k: v for k, v in a.items() if v is not None})


def _income_streams(a: dict) -> dict:
    return planner.income_streams_plan(get_profile())


def _real_estate(a: dict) -> dict:
    return planner.real_estate_plan(get_profile(), {k: v for k, v in a.items() if v is not None})


def _assumptions(a: dict) -> dict:
    return planner.assumptions_view()


def _fee_drag(a: dict) -> dict:
    from services import assumptions as asm

    return asm.fee_drag(
        float(a.get("balance") or 0.0),
        float(a.get("contribution") or 0.0),
        min(max(int(a.get("years") or 30), 1), 70),
        float(a["gross_return"]) if a.get("gross_return") is not None else 0.07,
        float(a["fee"]) if a.get("fee") is not None else asm.BY_KEY["fee.expense_ratio"]["default"],
    )


def _plan_health(a: dict) -> dict:
    return planner.plan_health(get_profile())


def _survivor(a: dict) -> dict:
    return planner.survivor_plan(get_profile(), {k: v for k, v in a.items() if v is not None})


def _scenarios(a: dict) -> dict:
    from models import Scenario

    return {"saved": [x.to_dict() for x in db.session().query(Scenario).order_by(Scenario.id)], "presets": scenarios.presets_public()}


def _compare_scenarios(a: dict) -> dict:
    from models import Scenario

    p = get_profile()
    ids = [int(i) for i in a.get("ids") or []]
    names = [n for n in a.get("presets") or [] if n in scenarios.PRESETS]
    saved = list(db.session().query(Scenario).filter(Scenario.id.in_(ids))) if ids else []
    return planner.scenario_compare(p, saved, [scenarios.preset(n, p, a.get("n")) for n in names])


def _tornado(a: dict) -> dict:
    return planner.scenario_tornado(get_profile())


def _solve(a: dict) -> dict:
    try:
        return planner.scenario_solve(get_profile(), a.get("kind") or "max_spend", a.get("target"))
    except ValueError as e:
        return {"error": str(e)}


def _event_templates(a: dict) -> dict:
    return {n: spending.event_from_template(n, date.today().year + 1)[0] for n in spending.template_names()}


def _savings(a: dict) -> dict:
    return planner.savings_plan(get_profile(), {k: v for k, v in a.items() if v is not None})


def _roth(a: dict) -> dict:
    names = [x for x in (a.get("modes") or []) if x in roth.MODES] or list(roth.MODES)
    return planner.roth_plan(
        get_profile(), names, detail=False, retire_age=a.get("retire_age"), bracket_rate=float(a.get("bracket_rate") or 0.12), until_age=a.get("until_age")
    )


def _rmd(a: dict) -> dict:
    from routes.rmd_routes import report

    return report(get_profile(), float(a.get("qcd_annual") or 0), float(a.get("real_return") or 0.03))


def _inherited(a: dict) -> dict:
    return rmd.inherited_schedule(
        float(a["balance"]),
        int(a["beneficiary_age"]),
        int(a["death_year"]),
        bool(a.get("owner_died_on_or_after_rbd")),
        eligible_designated=bool(a.get("eligible_designated")),
    )


def _early_access() -> dict:
    from routes.early_access_routes import accounts_report

    return {"accounts": accounts_report(get_profile()), "exceptions": early_access.exceptions(), "penalty_rate": 0.10}


def _sepp(a: dict) -> dict:
    return early_access.sepp_payment(
        float(a["balance"]), int(a["age"]), float(a.get("rate") or 0.05), a.get("method") or "amortization", a.get("table") or "single", a.get("mid_term_rate")
    )


def _roth_order(a: dict) -> dict:
    return early_access.roth_ordering(
        float(a.get("contributions") or 0),
        [{"year": int(c["year"]), "amount": float(c["amount"])} for c in a.get("conversions") or []],
        float(a.get("earnings") or 0),
        float(a["withdraw"]),
        float(a["age"]),
        int(a["year"]),
        int(a["roth_open_year"]),
    )


def _state_rules(a: dict) -> dict:
    code = a.get("state") or get_profile().state
    return {"rules": state_rules.rules_for(code), "community_engagement": state_rules.engagement(), "retrieved_on": state_rules.retrieved_on().isoformat()}


def _hsa(a: dict) -> dict:
    from datetime import date

    year = int(a.get("year") or date.today().year)
    age = float(a.get("age") or get_profile().current_age)
    family = bool(a.get("family"))
    return {"year": year, "family": family, "age": age, "annual_limit": hsa.annual_limit(year, family, age), "retrieved_on": hsa.retrieved_on().isoformat()}


def _tax_estimate(a: dict) -> dict:
    from routes.tax_routes import estimate

    return estimate(a)


def _liabilities_rows() -> list[Liability]:
    return db.session().query(Liability).order_by(Liability.id).all()


def _timeline() -> list[dict]:
    p = get_profile()
    return household.timeline(p, _liabilities_rows(), db.session().query(PlannedEvent).all(), retire_age=p.target_retirement_age)


def _payoffs() -> list[dict]:
    p = get_profile()
    return household.payoff_schedule(p, _liabilities_rows(), retire_age=p.target_retirement_age)


def _plan_menu(a: dict) -> list[dict]:
    rows = db.session().query(AllowedPlanMenu).filter_by(account_id=int(a["account_id"]))
    return [{c: getattr(m, c) for c in ("ticker_or_cusip", "fund_name", "asset_class", "expense_ratio")} for m in rows]


def _ingest_log(a: dict) -> list[dict]:
    rows = db.session().query(IngestionLog).order_by(IngestionLog.id.desc()).limit(min(int(a.get("limit") or 10), 50))
    return [
        {
            "filename": r.filename,
            "parser": r.parser,
            "rows": r.rows_parsed,
            "status": r.status,
            "message": r.message,
            "at": r.created_at.isoformat(),
            "undone": r.undone_at is not None,
        }
        for r in rows
    ]


def _gaps() -> dict:
    import re

    s = db.session()
    p = get_profile()
    gaps = []

    def gap(field: str, why: str, where: str):
        gaps.append({"field": field, "why": why, "where": where})

    if not p.annual_income:
        gap("annual_income", "Income is 0, so savings capacity and taxes are unknown", "Plan -> profile")
    if not p.monthly_expenses_current:
        gap("monthly_expenses_current", "Current spending is 0", "Plan -> profile")
    if not p.monthly_expenses_retirement:
        gap("monthly_expenses_retirement", "Retirement spending is 0, so success rates are meaningless", "Plan -> profile")
    if not p.social_security_monthly:
        gap("social_security_monthly", "No Social Security estimate for the primary", "Plan -> profile (ssa.gov statement)")
    if p.spouse_birth_date and not p.spouse_social_security_monthly:
        gap("spouse_social_security_monthly", "Spouse has no Social Security estimate", "Plan -> profile")
    if p.spouse_birth_date and not p.spouse_annual_income and not p.spouse_take_home_monthly:
        gap("spouse_annual_income", "Spouse income is 0", "Plan -> profile")
    if not p.aca_benchmark_premium_monthly:
        gap("aca_benchmark_premium_monthly", "Using an age-based ACA premium estimate rather than your marketplace quote", "Plan -> health care")
    accounts = s.query(Account).all()
    if not accounts:
        gap("accounts", "No accounts imported", "Portfolio -> drop a statement")
    for a in accounts:
        if not a.holdings:
            gap(f"account:{a.name}", "Account has no holdings", "Portfolio")
        if a.tax_bucket == early_access.PRETAX and a.id and not s.query(AllowedPlanMenu).filter_by(account_id=a.id).count():
            gap(f"plan_menu:{a.name}", "No plan menu entered, so fund swaps can't be graded", "Portfolio -> account menu")
    unmapped = [
        h.symbol
        for h in s.query(Holding).filter(Holding.proxy_ticker.is_(None))
        if h.asset_class != "MONEY_MARKET" and not re.fullmatch(r"[A-Z]{1,5}", h.symbol)
    ]
    if unmapped:
        gap("proxy_tickers", f"Holdings without a proxy ticker: {', '.join(unmapped[:10])}", "Portfolio -> map proxies")
    if not s.query(Liability).count():
        gap("liabilities", "No debts entered (fine if debt-free)", "Portfolio -> debts")
    if not s.query(Pension).count():
        gap("pension", "No pension entered (fine if none)", "Plan -> pension")
    from services.llm_router import get_config

    cfg = get_config()
    if not (cfg.api_key_encrypted or ""):
        gap("llm_key", "No LLM API key saved in Settings (an environment key may still be in use)", "Settings -> LLM Router")
    return {"gap_count": len(gaps), "gaps": gaps}


def _screener(a: dict) -> list[dict]:
    s = db.session()
    last = s.query(ScreenerResult).order_by(ScreenerResult.run_at.desc()).first()
    if not last:
        return []
    rows = s.query(ScreenerResult).filter_by(run_at=last.run_at).order_by(ScreenerResult.score.desc()).limit(min(int(a.get("limit") or 15), 30))
    return [r.metrics_json for r in rows]


def _notifications() -> dict:
    from services import scheduler

    cfg = db.session().get(NotificationConfig, 1)
    return {
        "discord_configured": bool(cfg and cfg.discord_webhook_encrypted),
        "smtp_configured": bool(cfg and cfg.smtp_host and cfg.smtp_to),
        "scheduler_runs": scheduler.RUNS,
    }


HANDLERS = {
    "get_profile": lambda a: _profile_dict(get_profile()),
    "get_accounts_and_holdings": lambda a: _accounts(),
    "get_allocation": lambda a: {
        **planner.barbell_summary(db.session()),
        "asset_class_weights": planner.portfolio_weights(db.session().query(Account).all()),
        "sectors": rp.portfolio_exposure(),
    },
    "run_fire_scenario": _fire,
    "get_planned_events": _events,
    "get_cash_signal": lambda a: _cash(),
    "get_market_snapshot": lambda a: market_data.macro_snapshot(current_app.config["FRED_API_KEY"]),
    "get_stock_snapshot": _stock,
    "what_if_add_position": lambda a: rp.what_if(a["symbol"], float(a["amount"])),
    "get_research_reports": _reports,
    "get_liabilities": lambda a: _liabilities(),
    "get_pensions": lambda a: _pensions(),
    "get_coverage_options": lambda a: _coverage_options(),
    "get_early_access": lambda a: _early_access(),
    "get_social_security_plan": _social_security,
    "get_savings_plan": _savings,
    "get_spending_projection": _spending,
    "get_healthcare_costs": _healthcare,
    "get_income_streams": _income_streams,
    "get_real_estate_plan": _real_estate,
    "get_survivor_plan": _survivor,
    "get_assumptions": _assumptions,
    "get_fee_drag": _fee_drag,
    "get_plan_health": _plan_health,
    "get_xray": lambda a: xray.portfolio_xray(),
    "list_scenarios": _scenarios,
    "compare_scenarios": _compare_scenarios,
    "get_sensitivity_tornado": _tornado,
    "solve_plan": _solve,
    "get_event_templates": _event_templates,
    "get_stress_tests": _stress,
    "get_withdrawal_strategies": _strategies,
    "get_roth_conversion_plan": _roth,
    "get_rmd_projection": _rmd,
    "get_inherited_rmd": _inherited,
    "get_withdrawal_plan": _withdrawals,
    "get_sepp_payment": _sepp,
    "get_roth_withdrawal_order": _roth_order,
    "get_state_health_rules": _state_rules,
    "get_hsa_limits": _hsa,
    "get_tax_estimate": _tax_estimate,
    "get_household_timeline": lambda a: _timeline(),
    "get_debt_payoff_schedule": lambda a: _payoffs(),
    "get_plan_menu": _plan_menu,
    "get_ingestion_log": _ingest_log,
    "get_spending_actuals": lambda a: transactions.actuals(get_profile(), months=int(a.get("months") or 12)),
    "get_data_gaps": lambda a: _gaps(),
    "get_action_items": lambda a: actions.feed(db.session(), get_profile(), include_hidden=bool(a.get("include_hidden"))),
    "get_chart_data": lambda a: (
        chart_data.cash_flow(db.session(), get_profile())
        if a.get("kind") == "cashflow"
        else chart_data.bracket_fill(
            float(a["magi"]) if a.get("magi") is not None else float(get_profile().annual_income or 0) + float(get_profile().spouse_annual_income or 0),
            get_profile().tax_filing_status,
            int(a["year"]) if a.get("year") else None,
        )
    ),
    "get_onboarding_status": lambda a: onboarding.status(db.session(), get_profile()),
    "get_screener_results": _screener,
    "get_sector_overview": lambda a: market_data.sector_strength(),
    "get_notification_status": lambda a: _notifications(),
    "get_net_worth_history": _history,
    "get_net_worth_summary": lambda a: networth.summary(db.session(), get_profile()),
    "get_performance": lambda a: performance.report(
        db.session(), get_profile(), market_data.get_closes, market_data.get_fundamentals, assume_contributions=bool(a.get("assume_contributions"))
    ),
    "get_rebalance_plan": lambda a: rebalance.report(db.session(), get_profile(), float(a.get("threshold") or rebalance.DEFAULT_THRESHOLD)),
    "get_cash_plan": lambda a: _cash_plan(a),
    "get_cash_backtest": lambda a: cash_backtest.run(),
    "get_dcf_sensitivity": lambda a: (
        research_watch.dcf_for(str(a.get("symbol", "")).upper()) or {"error": "no positive free cash flow / share count / growth to project"}
    ),
    "get_watchlist": lambda a: research_watch.watchlist_view(db.session()),
    "get_theses": lambda a: research_watch.theses_view(db.session()),
    "get_insider_activity": lambda a: research_watch.insiders_for(str(a.get("symbol", "")).upper(), current_app.config["EDGAR_IDENTITY"]),
    "get_risk_report": lambda a: risk.report(db.session(), market_data.get_closes),
    "get_tax_lot_report": lambda a: tax_lots.report(db.session(), get_profile()),
    "suggest_lot_sale": lambda a: _suggest_lot_sale(a),
    "grade_401k_menu": _menu,
}


def _cash_plan(a: dict) -> dict:
    p = get_profile()
    market, _ = market_data.market_inputs(current_app.config["FRED_API_KEY"])
    mmf = p.current_money_market_yield if p.money_market_yield_override else max(market.tbill_3m - 0.0015, 0)
    opts = {k: float(a[k]) for k in ("ladder_amount", "cd_yield", "ibond_rate") if a.get(k) is not None}
    return cash_plan.build(db.session(), p, market, mmf, opts)


def _suggest_lot_sale(a: dict) -> dict:
    from datetime import date

    s = db.session()
    accounts = {x.id: x for x in s.query(Account).all()}
    prices = {(h.account_id, h.symbol): h.current_price for h in s.query(Holding).all() if h.current_price}
    lots = s.query(TaxLot).all()
    today = date.today()
    views = [tax_lots.lot_view(lot, prices, today) for lot in lots]
    return tax_lots.suggest_sale(views, str(a["symbol"]), float(a["amount"]), get_profile(), today, lots, accounts, a.get("account_id"))


def dispatch(name: str, args: dict) -> str:
    fn = HANDLERS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        out = json.dumps(fn(args), default=str)
    except Exception as e:
        out = json.dumps({"error": f"{type(e).__name__}: {e}"})
    return out if len(out) <= MAX_RESULT_CHARS else out[:MAX_RESULT_CHARS] + '..."[truncated]'
