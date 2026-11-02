"""Core-vs-Satellite partitioning, 401(k) menu optimizer, and FIRE orchestration over DB data."""

import math
from datetime import date
from types import SimpleNamespace

import db
from models import Account, AssumptionOverride, CoverageOption, Liability, Pension, PlannedEvent, RunSnapshot, SpendingGoal
from services import aca, cash_optimizer, household, income_streams, ingestion, state_rules
from services import assumptions as assumptions_svc
from services import coverage as coverage_svc
from services import healthcare as healthcare_svc
from services import liabilities as liab_svc
from services import pension as pension_svc
from services import quant_engine as qe
from services import real_estate as real_estate_svc
from services import rmd as rmd_svc
from services import roth as roth_svc
from services import savings as sav_svc
from services import scenarios as scen_svc
from services import social_security as ss_svc
from services import spending as spending_svc
from services import stress as stress_svc
from services import survivor as survivor_svc
from services import withdrawal_strategies as ws
from services import withdrawals as wd

TIER_SPLITS = {  # share of satellite surplus per sleeve, by risk appetite (speculative share)
    "compounders": lambda spec: 1 - spec,
    "asymmetric": lambda spec: spec,
}


def allocate_surplus(surplus: float, risk_appetite: float) -> dict:
    spec = min(max(risk_appetite, 0.0), 1.0)
    return {
        "High-Conviction Compounders": round(surplus * (1 - spec), 2),
        "Asymmetric Growth / Momentum": round(surplus * spec, 2),
    }


def grade_menu(menu: list[dict], holdings: list[dict]) -> dict:
    """Grade a restricted 401(k): flag costly holdings, suggest the cheapest same-asset-class fund on the menu."""
    cheapest: dict[str, dict] = {}
    for m in menu:
        c = cheapest.get(m["asset_class"])
        if c is None or m["expense_ratio"] < c["expense_ratio"]:
            cheapest[m["asset_class"]] = m
    by_sym = {m["ticker_or_cusip"]: m for m in menu}
    total = sum(h["market_value"] for h in holdings) or 1.0
    suggestions, weighted_er, potential = [], 0.0, 0.0
    for h in holdings:
        m = by_sym.get(h["symbol"])
        er = m["expense_ratio"] if m else 0.0
        weighted_er += er * h["market_value"] / total
        best = cheapest.get(h["asset_class"])
        if m and best and best["ticker_or_cusip"] != h["symbol"] and er - best["expense_ratio"] >= 0.002:
            saving = (er - best["expense_ratio"]) * h["market_value"]
            potential += saving
            suggestions.append(
                {
                    "from": h["symbol"],
                    "to": best["ticker_or_cusip"],
                    "to_name": best["fund_name"],
                    "er_from": er,
                    "er_to": best["expense_ratio"],
                    "annual_savings": round(saving, 2),
                }
            )
    grade = "A" if weighted_er < 0.0015 else "B" if weighted_er < 0.003 else "C" if weighted_er < 0.006 else "D"
    return {"weighted_expense_ratio": weighted_er, "grade": grade, "suggestions": suggestions, "annual_savings_potential": round(potential, 2)}


def portfolio_weights(accounts) -> dict[str, float]:
    w: dict[str, float] = {}
    for a in accounts:
        for h in a.holdings:
            w[h.asset_class] = w.get(h.asset_class, 0.0) + h.market_value
    return w


def _gain_ratio(accts) -> float:
    """Share of a taxable-brokerage withdrawal that is realized gain (counts toward ACA income)."""
    mv = cost = 0.0
    for a in accts:
        if a.tax_bucket != "TAXABLE_BROKERAGE":
            continue
        for h in a.holdings:
            if h.cost_basis_total > 0:
                mv += h.market_value
                cost += h.cost_basis_total
    return min(max((mv - cost) / mv, 0.0), 1.0) if mv > 0 else 0.3


def hsa_balance(accts) -> float:
    """HSA value: an earmarked medical reserve, kept out of the bridge (taxable) and pre-tax pools."""
    return sum(h.market_value for a in accts if a.tax_bucket == "HSA" for h in a.holdings)


def _pools(accts):
    taxable = pretax = pretax_sp = 0.0
    tax_w: dict[str, float] = {}
    pre_w: dict[str, float] = {}
    for a in accts:
        if a.tax_bucket == "HSA":
            continue
        for h in a.holdings:
            if a.tax_bucket == "PRE_TAX_401K":
                if a.owner == "SPOUSE":
                    pretax_sp += h.market_value
                else:
                    pretax += h.market_value
                pre_w[h.asset_class] = pre_w.get(h.asset_class, 0) + h.market_value
            else:  # taxable, Roth principal approximated as bridge-eligible, cash
                taxable += h.market_value
                tax_w[h.asset_class] = tax_w.get(h.asset_class, 0) + h.market_value
    return taxable, pretax, pretax_sp, tax_w, pre_w


def _rule55_locked(accts) -> float:
    """Primary pre-tax balance the Rule of 55 cannot reach. Only applies once the user has flagged their current-employer plan;
    until then every primary plan is assumed reachable (the previous behaviour)."""
    mine = [a for a in accts if a.tax_bucket == "PRE_TAX_401K" and a.owner != "SPOUSE"]
    if not any(a.is_current_employer_plan for a in mine):
        return 0.0
    return sum(h.market_value for a in mine if not a.is_current_employer_plan for h in a.holdings)


def stored_overrides() -> dict[str, float]:
    return {o.key: o.value for o in db.session().query(AssumptionOverride).all()}


def build_inputs(profile, accts, debts, events, retire_age: float, rule_of_55=False, guardrails=None, goals=None):
    """FireInputs + household flows for one candidate retirement age."""
    assumptions_svc.apply(stored_overrides())
    taxable, pretax, pretax_sp, tax_w, pre_w = _pools(accts)
    mu_t, sg_t = qe.expected_return_vol(tax_w or {"US_EQUITY": 1})
    mu_p, sg_p = qe.expected_return_vol(pre_w or {"US_EQUITY": 1})
    years = math.ceil(95 - profile.current_age)
    fl = household.build_flows(
        profile,
        debts,
        events,
        retire_age=retire_age,
        years=years,
        inflation=qe.INFLATION,
        taxable_now=taxable,
        real_return_taxable=(1 + mu_t) / (1 + qe.INFLATION) - 1,
        gain_ratio=_gain_ratio(accts),
        coverage_options=db.session().query(CoverageOption).all(),
        spending_goals=db.session().query(SpendingGoal).all() if goals is None else goals,
    )
    pretax_other = _rule55_locked(accts) if rule_of_55 else 0.0
    pretax -= pretax_other
    has_sp = profile.spouse_age > 0
    # spouse's pre-tax pool opens when the *spouse* turns 59.5, expressed in the primary's age
    spouse_unlock = profile.current_age + max(59.5 - profile.spouse_age, 0) if has_sp else None
    annual_contrib = profile.monthly_contribution * 12
    inp = qe.FireInputs(
        current_age=profile.current_age,
        retire_age=retire_age,
        taxable=taxable,
        pretax=pretax,
        pretax_spouse=pretax_sp,
        pretax_other=pretax_other,
        spouse_unlock_age=spouse_unlock,
        other_income_after=fl.ss_self[0],
        other_income_start=fl.ss_self[1],
        other_income_spouse=fl.ss_spouse[0] if has_sp else 0.0,
        other_income_spouse_start=fl.ss_spouse[1] if has_sp else 67,
        annual_contribution_bridge=annual_contrib * 0.4,
        annual_contribution_pretax=annual_contrib * 0.6,
        retirement_spend=profile.monthly_expenses_retirement * 12,
        tax_rate=profile.effective_tax_rate,
        debt_service_by_year=[float(x) for x in fl.debt_nominal] if fl.debt_nominal.any() else None,
        extra_spend_by_year=[float(x) for x in fl.extra_spend],
        income_by_year=[float(x) for x in fl.income],
        contrib_bridge_by_year=[float(x) for x in fl.contrib_bridge],
        contrib_pretax_by_year=[float(x) for x in fl.contrib_pretax],
        contrib_pretax_spouse_by_year=[float(x) for x in fl.contrib_pretax_spouse],
        guardrails=bool(profile.guardrails_enabled if guardrails is None else guardrails),
        mu_taxable=mu_t,
        sigma_taxable=sg_t,
        mu_pretax=mu_p,
        sigma_pretax=sg_p,
        rule_of_55=rule_of_55,
    )
    return inp, fl


def _phases(profile, inp: qe.FireInputs, fl, spend: float) -> list[dict]:
    """Monthly budget and where the money comes from in each stage of retirement (today's dollars)."""
    ppl = household.people(profile, inp.retire_age)
    me = ppl[0]
    marks = {inp.retire_age: "Retirement begins"}
    for p in ppl:
        for own_age, label in (
            (household.UNLOCK_AGE, f"{p.name}'s 401(k) unlocks"),
            (household.MEDICARE_AGE, f"{p.name} on Medicare"),
            (p.ss_claim_age, f"{p.name}'s Social Security starts"),
        ):
            a = me.age_now + p.years_until(own_age)
            if a > inp.retire_age + 0.01 and a < inp.end_age:
                marks[a] = f"{marks[a]} · {label}" if a in marks else label
    if len(ppl) > 1 and ppl[1].retire_age and (a := me.age_now + ppl[1].years_until(ppl[1].retire_age)) > inp.retire_age + 0.01:
        marks[a] = f"{ppl[1].name} retires"
    starts = sorted(marks)
    out = []
    net = max(1 - inp.tax_rate, 0.05)
    for i, a in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else inp.end_age
        y0 = household.year_index(a - inp.current_age)
        y1 = max(household.year_index(end - inp.current_age), y0 + 1)
        ys = range(y0, min(y1, fl.years))
        if not ys:
            continue
        avg = lambda v: float(sum(v[y] for y in ys) / len(ys))
        debt_real = [fl.debt_nominal[y] / (1 + qe.INFLATION) ** y for y in range(fl.years)]
        health = avg(fl.breakdown["health"])
        housing = avg(fl.breakdown["home_upkeep"]) + avg(fl.breakdown["escrow"])
        purchases = avg(fl.breakdown["purchases"])
        ltc = avg(fl.breakdown["ltc"])
        debt = avg(debt_real)
        gross = (spend + health + housing + purchases + ltc + debt) / net
        ss_me = fl.ss_self[0] if a >= fl.ss_self[1] - 1e-9 else 0.0
        ss_sp = fl.ss_spouse[0] if (len(ppl) > 1 and a >= fl.ss_spouse[1] - 1e-9) else 0.0
        other = avg(fl.income)
        portfolio = max(gross - ss_me - ss_sp - other, 0.0)
        m = lambda x: round(x / 12, 2)
        out.append(
            {
                "label": marks[a],
                "start_age": round(a, 1),
                "end_age": round(end, 1),
                "start_year": date.today().year + y0,
                "ages": {p.key: round(p.age_now + (a - me.age_now), 1) for p in ppl},
                "spending": {
                    "living": m(spend),
                    "health_care": m(health),
                    "housing": m(housing),
                    "planned_purchases": m(purchases),
                    "long_term_care": m(ltc),
                    "debt": m(debt),
                    "taxes": m(gross - gross * net),
                },
                "sources": {"portfolio": m(portfolio), "social_security_self": m(ss_me), "social_security_spouse": m(ss_sp), "other_income": m(other)},
                "total_monthly": m(gross),
            }
        )
    return out


def run_fire(profile, n_sims=5000, rule_of_55=False, seed=42, events=None, guardrails=None, detail=True, shock=0.0, goals=None) -> dict:
    s = db.session()
    accts = s.query(Account).all()
    rule_of_55 = rule_of_55 or any(
        a.is_current_employer_plan and a.tax_bucket == "PRE_TAX_401K" and a.owner != "SPOUSE" for a in accts
    )  # flagging your plan opts in
    debts = s.query(Liability).all()
    base_events = s.query(PlannedEvent).all() if events is None else events
    pensions = s.query(Pension).all() if events is None else []

    def events_for(age):  # pension benefits move with the retirement age being tried
        return [*base_events, *pension_svc.virtual_events(pensions, profile, age)]

    events = events_for(profile.target_retirement_age)
    target = getattr(profile, "target_success_rate", 0.85) or 0.85
    retire = profile.target_retirement_age

    def rebuild(age):
        return build_inputs(profile, accts, debts, events_for(age), age, rule_of_55, guardrails, goals)[0]

    inp, fl = build_inputs(profile, accts, debts, events, retire, rule_of_55, guardrails, goals)
    inp.first_year_shock = shock
    sim = qe.simulate_fire(inp, n_sims=n_sims, seed=seed)
    y0 = max(math.ceil(retire - profile.current_age), 0)
    unlocks = [59.5] + ([inp.spouse_unlock_age] if inp.pretax_spouse > 0 and inp.spouse_unlock_age is not None else [])
    bridge_end = min(unlocks)
    extra_real = [float(fl.debt_nominal[y]) / (1 + qe.INFLATION) ** y + fl.extra_spend[y] - fl.income[y] for y in range(y0, fl.years)]
    need = qe.bridge_capital_needed(retire, inp.retirement_spend, inp.tax_rate, unlock_age=bridge_end, debt_real_by_year=extra_real)
    have = sim["median_bridge_capital_at_retirement"]
    years_to = max(retire - profile.current_age, 0)
    have_real = have / (1 + qe.INFLATION) ** years_to  # today's dollars, comparable with the need
    has_costs = inp.retirement_spend > 0 or debts or any(fl.extra_spend)
    earliest = qe.earliest_retirement_age(inp, target_success=target, rebuild=rebuild) if (has_costs and detail) else None
    ppl = household.people(profile, retire)
    out = {
        **sim,
        "inputs": {
            "taxable": inp.taxable,
            "pretax": inp.pretax,
            "pretax_spouse": inp.pretax_spouse,
            "hsa": hsa_balance(accts),  # medical reserve, not in the bridge
            "spouse_unlock_age_in_your_terms": inp.spouse_unlock_age,
            "mu_taxable": inp.mu_taxable,
            "mu_pretax": inp.mu_pretax,
        },
        "bridge_capital_needed": need,
        "bridge_capital_projected_real": have_real,
        "bridge_readiness_pct": min(have_real / need * 100, 999) if need > 0 else 100.0,
        "target_success_rate": target,
        "earliest_retirement_age": earliest,
        "earliest_ages": {p.key: round(p.age_now + (earliest - profile.current_age), 1) for p in ppl} if earliest else None,
        "people": [{"key": p.key, "name": p.name, "age_now": round(p.age_now, 1), "retire_age": round(p.retire_age, 1)} for p in ppl],
    }
    this_year = date.today().year
    out["path"] = [
        {"year": this_year + i, "ages": {p.key: round(p.age_now + i, 1) for p in ppl}, "value": v, **sim["path_bands_real"][i]}
        for i, (_, v) in enumerate(sim["median_path_real"])
    ]
    if not detail:
        return out
    spend = qe.sustainable_spend(inp, target_success=target)
    out["sustainable_spend_monthly"] = round(spend / 12, 2)
    out["planned_spend_monthly"] = profile.monthly_expenses_retirement
    # Phases show the sustainable budget; when nothing is sustainable at this age, show the planned budget's shortfall instead
    out["monthly_income_basis"] = "SUSTAINABLE" if spend > 0 else "PLANNED"
    out["monthly_income"] = _phases(profile, inp, fl, spend if spend > 0 else inp.retirement_spend)
    out["sustainable_spend_at_earliest_monthly"] = None
    if earliest is not None and abs(earliest - retire) >= 0.5:
        out["sustainable_spend_at_earliest_monthly"] = round(qe.sustainable_spend(rebuild(earliest), target_success=target) / 12, 2)
    out["timeline"] = household.timeline(profile, debts, events, retire_age=retire)
    out["debts"] = household.payoff_schedule(profile, debts, retire_age=retire)
    out["health"] = [h for h in fl.health if h["coverage"] != "EMPLOYER" or h["year"] >= this_year + y0][:40]
    cliff_years = [h for h in out["health"] if h.get("over_cliff")]
    notes = []
    if cliff_years:
        notes.append(
            f"Estimated income is above the ACA subsidy cliff (${cliff_years[0]['cliff_magi']:,.0f}) in "
            f"{len(cliff_years)} year(s) before Medicare, so you'd pay full price. Drawing more from cash/Roth or "
            f"low-gain shares in those years could keep income under the cliff."
        )
    blocked = [h for h in out["health"] if h.get("engagement_blocked")]
    if blocked:
        notes.append(
            f"In {len(blocked)} year(s) your income is low enough for {blocked[0]['medicaid_agency']}, but from 2027 adults 19-64 must show "
            f"80 hours a month of work, volunteering, training or school. Without that you lose Medicaid and the marketplace credit too, "
            f"so those years are priced at full ACA cost. Turn on the community-engagement setting if you plan to meet it."
        )
    if any(h.get("medicaid") for h in out["health"]):
        notes.append("Medicaid depends on your actual taxable income, including interest and dividends you don't choose to realize.")
    if any(h.get("coverage_gap") for h in out["health"]):
        notes.append("Your state didn't expand Medicaid: income below the poverty line gets no Medicaid and no marketplace credit.")
    out["aca_note"] = " ".join(notes) or None
    return out


def barbell_summary(s) -> dict:
    t = ingestion.bucket_totals(s)
    total = sum(t.values()) or 1.0
    debt = liab_svc.total_balance(s.query(Liability).all())
    return {"totals": t, "pct": {k: v / total for k, v in t.items()}, "assets": sum(t.values()), "liabilities": debt, "net_worth": sum(t.values()) - debt}


def cash_recommendation(s, profile, mmf_yield: float, market) -> dict:
    """Cash-vs-market call with an essentials-based buffer and high-APR debt retired before anything is deployed."""
    debts = s.query(Liability).all()
    high_apr = sum(d.balance for d in debts if d.apr >= liab_svc.HIGH_APR)
    return cash_optimizer.recommend(
        ingestion.cash_total(s), liab_svc.essential_monthly(profile, debts), profile.emergency_fund_target_months, mmf_yield, market, high_apr_debt=high_apr
    )


def _bucket_values(accts) -> dict[str, float]:
    out = {"taxable": 0.0, "pretax": 0.0, "roth": 0.0}
    for a in accts:
        v = sum(h.market_value for h in a.holdings)
        key = {"PRE_TAX_401K": "pretax", "ROTH": "roth", "HSA": None}.get(a.tax_bucket, "taxable")
        if key:
            out[key] += v
    return out


def withdrawal_inputs(profile, accts, debts, events, retire_age: float, today: date | None = None) -> wd.Inputs:
    """Translate the household into the sequencing simulator's real-dollar inputs (balances grown to retirement)."""
    today = today or date.today()
    inp, fl = build_inputs(profile, accts, debts, events, retire_age, False, None)
    ppl = household.people(profile, retire_age)
    me = ppl[0]
    r0 = fl.retire_y
    b = _bucket_values(accts)
    mu_t, mu_p = inp.mu_taxable, inp.mu_pretax
    real_t, real_p = (1 + mu_t) / (1 + qe.INFLATION) - 1, (1 + mu_p) / (1 + qe.INFLATION) - 1
    taxable, pretax, roth = b["taxable"], b["pretax"], b["roth"]
    for y in range(r0):  # accumulate in real terms to the first retirement year
        taxable = taxable * (1 + real_t) + float(fl.contrib_bridge[y])
        pretax = pretax * (1 + real_p) + float(fl.contrib_pretax[y] + fl.contrib_pretax_spouse[y])
        roth *= 1 + real_t
    n = max(fl.years - r0, 0)
    net = max(1 - profile.effective_tax_rate, 0.05)
    spend, ss, ordinary, cash, bench = [], [], [], [], []
    sp = ppl[1] if len(ppl) > 1 else None
    st = state_rules.rules_for(getattr(profile, "state", "AZ"))
    for i in range(n):
        y = r0 + i
        other_health = 0.0
        row = fl.health[i] if i < len(fl.health) else {}
        other_health = row.get("dental_vision", 0.0) + row.get("out_of_pocket", 0.0) + row.get("medicare", 0.0)
        extras = float(fl.breakdown["purchases"][y] + fl.breakdown["home_upkeep"][y] + fl.breakdown["escrow"][y] + fl.breakdown["ltc"][y])
        debt = float(fl.debt_nominal[y]) / (1 + qe.INFLATION) ** y
        spend.append(profile.monthly_expenses_retirement * 12 + extras + debt + other_health)
        ss.append((fl.ss_self[0] if me.age_in(y) >= fl.ss_self[1] else 0.0) + (fl.ss_spouse[0] if sp and me.age_in(y) >= fl.ss_spouse[1] else 0.0))
        ordinary.append(float(fl.breakdown["pensions"][y] + fl.breakdown["spouse_wages"][y] / net))
        cash.append(float(fl.breakdown["inflows"][y]))
        under = [p for p in ppl if p.age_in(y) < household.MEDICARE_AGE]
        override = getattr(profile, "aca_benchmark_premium_monthly", 0) or 0
        bench.append((override * 12 * len(under) / len(ppl)) if (override and under) else aca.benchmark_annual([p.age_in(y) for p in under]) if under else 0.0)
    return wd.Inputs(
        start_year=today.year + r0,
        start_age=retire_age if r0 == 0 else me.age_now + r0,
        end_age=95,
        status=getattr(profile, "tax_filing_status", "SINGLE"),
        state=getattr(profile, "state", None),
        household_size=len(ppl),
        taxable=taxable,
        pretax=pretax,
        roth=roth,
        gain_ratio=_gain_ratio(accts),
        real_return=real_t,
        spend=spend,
        ss=ss,
        ordinary_income=ordinary,
        other_cash=cash,
        aca_benchmark=bench,
        pretax_access_age=55.0 if any(a.is_current_employer_plan and a.tax_bucket == "PRE_TAX_401K" for a in accts) else household.UNLOCK_AGE,
        medicaid_limit=st["adult_limit_fpl"] if st["medicaid_expansion"] else None,
    )


def social_security_plan(profile, haircut: float = 0.0, haircut_year: int | None = None, real_rate: float = 0.02, modal: float = 88.0) -> dict:
    def person(name, birth, age_now, monthly, claim):
        return {"name": name, "birth_year": birth.year, "age_now": age_now, "pia": monthly, "claim_age": float(claim or 67)}

    a = person("You", profile.birth_date, profile.current_age, profile.social_security_monthly, getattr(profile, "ss_claim_age", 67))
    b = None
    if profile.spouse_birth_date:
        b = person("Spouse", profile.spouse_birth_date, profile.spouse_age, profile.spouse_social_security_monthly, getattr(profile, "spouse_ss_claim_age", 67))
    out = ss_svc.grid(a, b, real_rate=real_rate, modal=modal, haircut=haircut, haircut_year=haircut_year)
    out["monthly_benefit_is_pia"] = True
    return out


def savings_plan(profile, p: dict | None = None) -> dict:
    """Contribution limits, the savings waterfall and FI variants for the household, with optional overrides in `p`."""
    p = p or {}
    s = db.session()
    accts = s.query(Account).all()
    year = int(p.get("year") or date.today().year)
    status = profile.tax_filing_status if profile.tax_filing_status in ("SINGLE", "MFJ") else "SINGLE"
    salary = float(p.get("salary") if p.get("salary") is not None else profile.annual_income)
    saving = float(p.get("annual_saving") if p.get("annual_saving") is not None else profile.monthly_contribution * 12)
    magi = float(p["magi"]) if p.get("magi") is not None else salary + (profile.spouse_annual_income if status == "MFJ" else 0.0)
    balance = sum(h.market_value for a in accts if a.tax_bucket != "HSA" for h in a.holdings)
    pretax_ira = float(p.get("pretax_ira_balance") or 0.0)  # accounts have no separate IRA bucket, so the user supplies it
    spend = float(p["annual_spend"]) if p.get("annual_spend") is not None else profile.monthly_expenses_retirement * 12
    age = profile.current_age
    out = {
        "waterfall": sav_svc.waterfall(
            saving,
            salary,
            age,
            year,
            status,
            magi,
            float(p.get("match_rate") or 0.0),
            float(p.get("match_cap_pct") or 0.0),
            bool(p.get("hsa_eligible")),
            bool(p.get("hsa_family")),
            float(p.get("employer_contrib") or 0.0),
            bool(p.get("prefer_roth_401k")),
            bool(p.get("mega_backdoor")),
            not p.get("not_covered_by_plan"),
        ),
        "checklist": sav_svc.backdoor_checklist(pretax_ira, bool(p.get("plan_allows_after_tax")), bool(p.get("plan_allows_in_service"))),
        "fi": sav_svc.fi_variants(
            spend,
            balance,
            saving,
            age,
            profile.target_retirement_age,
            float(p.get("real_return") or 0.05),
            float(p.get("withdrawal_rate") or 0.04),
            float(p.get("part_time_income") or 0.0),
        ),
        "inputs": {"salary": salary, "annual_saving": saving, "magi": magi, "investable_balance": balance, "annual_spend": spend, "age": age, "status": status},
    }
    return out


def roth_plan(profile, modes=roth_svc.MODES, detail=True, retire_age: float | None = None, bracket_rate: float = 0.12, until_age: float | None = None) -> dict:
    s = db.session()
    accts = s.query(Account).all()
    retire = retire_age or profile.target_retirement_age
    events = [*s.query(PlannedEvent).all(), *pension_svc.virtual_events(s.query(Pension).all(), profile, retire)]
    inp = withdrawal_inputs(profile, accts, s.query(Liability).all(), events, retire)
    birth = getattr(profile, "birth_date", None)
    rmd_age = rmd_svc.start_age(birth.year) if birth else 75
    out = roth_svc.compare(
        inp, tuple(modes), detail=detail, bracket_rate=bracket_rate, until_age=until_age if until_age is not None else rmd_age - 1, rmd_start_age=rmd_age
    )
    out["retire_age"] = retire
    out["starting_balances"] = {"taxable": inp.taxable, "pretax": inp.pretax, "roth": inp.roth}
    return out


def _retirement_setup(profile, p: dict) -> tuple[ws.Setup, object, float, str]:
    """Retirement-date portfolio, real-return assumptions and income stream shared by the policy and stress engines."""
    s = db.session()
    accts = s.query(Account).all()
    retire = float(p.get("retire_age") or profile.target_retirement_age)
    events = [*s.query(PlannedEvent).all(), *pension_svc.virtual_events(s.query(Pension).all(), profile, retire)]
    inp, _ = build_inputs(profile, accts, s.query(Liability).all(), events, retire, False, None)
    end = float(p.get("end_age") or inp.end_age)
    years = max(math.ceil(end - retire), 1)
    pools = inp.taxable + inp.pretax + inp.pretax_spouse + inp.pretax_other
    if p.get("portfolio") is not None:
        portfolio, source = float(p["portfolio"]), "supplied"
    else:
        path = run_fire(profile, n_sims=600, seed=int(p.get("seed") or 42), detail=False).get("median_path_real") or []
        at = [v for a, v in path if a >= retire]
        portfolio, source = (float(at[0]) if at else pools), "median projected balance at retirement (today's dollars)"
    w_t = inp.taxable / pools if pools > 0 else 1.0
    mu_nom = w_t * inp.mu_taxable + (1 - w_t) * inp.mu_pretax
    sigma = w_t * inp.sigma_taxable + (1 - w_t) * inp.sigma_pretax
    mu = (1 + mu_nom) / (1 + inp.inflation) - 1
    income = [
        (inp.other_income_after if retire + t >= inp.other_income_start else 0.0)
        + (inp.other_income_spouse if retire + t >= inp.other_income_spouse_start else 0.0)
        for t in range(years)
    ]
    setup = ws.Setup(
        portfolio=portfolio,
        years=years,
        mu=float(p["mu"]) if p.get("mu") is not None else mu,
        sigma=float(p["sigma"]) if p.get("sigma") is not None else sigma,
        income=income,
        n_sims=int(p.get("n_sims") or 2000),
        seed=int(p.get("seed") or 42),
    )
    return setup, inp, retire, source


def strategy_plan(profile, policies=ws.POLICIES, p: dict | None = None) -> dict:
    """Withdrawal-policy comparison and safe-spend solver on the plan's retirement-date portfolio (real dollars)."""
    p = p or {}
    setup, inp, retire, source = _retirement_setup(profile, p)
    out = ws.compare(setup, tuple(p.get("targets") or (0.90, 0.95)), tuple(policies), detail=bool(p.get("detail", True)))
    net = max(1 - inp.tax_rate, 0.05)
    for row in out["policies"]:
        row["safe_spend_after_tax"] = {k: v * net for k, v in row["safe_spend"].items()}
    cur = inp.retirement_spend / net
    out.update(
        retire_age=retire, portfolio_source=source, tax_rate=inp.tax_rate, current_plan_spend_gross=cur, current_plan_spend_after_tax=inp.retirement_spend
    )
    return out


def stress_plan(profile, p: dict | None = None) -> dict:
    """Sequence-of-returns stress tests on the plan's retirement-date portfolio."""
    p = p or {}
    setup, inp, retire, source = _retirement_setup(profile, p)
    net = max(1 - inp.tax_rate, 0.05)
    s0 = float(p["spend"]) if p.get("spend") is not None else inp.retirement_spend / net
    starts = tuple(int(x) for x in p.get("starts") or stress_svc.DEFAULT_STARTS)
    out = stress_svc.stress(setup, s0, float(p.get("equity") or 0.6), p.get("policy") or "fixed_real", starts)
    out.update(retire_age=retire, portfolio_source=source)
    return out


def spending_plan(profile, nominal: bool = False, base_annual: float | None = None, smile: bool | None = None) -> dict:
    """Retirement base spending by year and category under the profile's spending model (real or nominal)."""
    m = spending_svc.load(getattr(profile, "spending_model", None))
    if smile is not None:
        m = m.model_copy(update={"smile": smile})
    base = profile.monthly_expenses_retirement * 12 if base_annual is None else base_annual
    out = spending_svc.projection(m, base, profile.current_age, profile.target_retirement_age, 95, qe.INFLATION, nominal)
    out["base_annual"] = base
    out["model"] = {"smile": m.smile, "shares": spending_svc.shares(m), "real_inflation": spending_svc.real_inflation(m), "phases": spending_svc.phases(m)}
    out["health_note"] = "Health care is priced separately with its own inflation (health_inflation) and is not in these categories."
    return out


def coverage_comparison(profile, year: int, magi: float) -> list[dict]:
    """Per person: ACA net premium (pre-65) next to each eligible custom option's annual cost, today's dollars."""
    opts = db.session().query(CoverageOption).order_by(CoverageOption.sort_order, CoverageOption.id).all()
    ppl = household.people(profile)
    ages = {p.key: p.age_now for p in ppl}
    aca_net = {}
    for k, a in ages.items():
        if a < household.MEDICARE_AGE:
            aca_net[k] = healthcare_svc.pre65_table([int(a)], magi, len(ppl))[0]["net"]
    return coverage_svc.compare(opts, {o.id: o for o in opts if o.category == "DRUG"}, ages, year, aca_net)


def healthcare_plan(profile, p: dict | None = None) -> dict:
    """Medicare (Part B/D, IRMAA, Medigap), pre-65 ACA premiums by age, HSA run-out and LTC expected/stress cost."""
    p = p or {}
    status = p.get("status") or getattr(profile, "tax_filing_status", "SINGLE")
    year = int(p.get("year") or date.today().year)
    magi = float(p.get("magi") if p.get("magi") is not None else 0.0)
    people = int(p.get("people") or (2 if status == "MFJ" else 1))
    ages = [int(a) for a in (p.get("ages") or range(50, 65, 2))]
    ltc_cost = float(p.get("ltc_annual") if p.get("ltc_annual") is not None else profile.ltc_annual)
    ltc_years = float(p.get("ltc_years") if p.get("ltc_years") is not None else profile.ltc_years)
    out = healthcare_svc.plan(magi, status, year, people, ages, ltc_cost, ltc_years)
    hsa_bal = float(p.get("hsa_balance") or 0.0)
    out["hsa"] = healthcare_svc.hsa_projection(
        hsa_bal, people > 1, profile.current_age, profile.target_retirement_age, 95, year, medical_spend=float(p.get("hsa_medical_spend") or 0.0)
    )
    out["magi_basis"] = "current-year estimate you pass in; real IRMAA uses MAGI from two years earlier"
    out["coverage_options"] = coverage_comparison(profile, year, magi)
    return out


def income_streams_plan(profile, horizon: int = 40) -> dict:
    """Per-year gross, taxable and after-tax cash from the user's taxed income-stream events (annuity, part-time, rental, equity, inheritance, sale)."""
    s = db.session()
    this_year = date.today().year
    status = getattr(profile, "tax_filing_status", "SINGLE")
    events = [e for e in s.query(PlannedEvent).all() if e.kind in income_streams.STREAM_KINDS]
    parts: dict[int, list[dict]] = {}
    for ev in events:
        for y in household.event_years(ev, this_year, horizon):
            parts.setdefault(y, []).append(income_streams.components(ev.kind, ev.amount, ev.basis or 0.0, max(this_year + y - ev.start_year, 0)))
    rows = [
        {"year": this_year + y} | income_streams.after_tax(p, 0.0, status, this_year + y, getattr(profile, "state", None)) for y, p in sorted(parts.items())
    ]
    return {
        "events": [e.to_dict() for e in events],
        "years": rows,
        "notes": income_streams.__doc__,
        "base_income_note": "Tax is incremental over zero other income here; the plan itself stacks on pension income.",
    }


def real_estate_plan(profile, p: dict | None = None) -> dict:
    """Home equity path, paydown-vs-invest per debt, a downsizing what-if and an optional relocation cost-of-living comparison."""
    p = p or {}
    s = db.session()
    liabs = s.query(Liability).order_by(Liability.id).all()
    status = p.get("status") or getattr(profile, "tax_filing_status", "SINGLE")
    year = date.today().year
    d = real_estate_svc.defaults()
    appr = float(p["appreciation"]) if p.get("appreciation") is not None else d["appreciation"]
    homes = [x for x in liabs if x.kind == "MORTGAGE"]
    value = float(p["home_value"]) if p.get("home_value") is not None else float(profile.home_value)
    mort = [{"balance": m.balance, "apr": m.apr, "monthly_payment": m.monthly_payment} for m in homes]
    mmf, equity_ret = profile.current_money_market_yield, qe.ASSET_ASSUMPTIONS["US_EQUITY"][0]
    out = {
        "defaults": d,
        "home_value": value,
        "mortgage_balance": sum(m["balance"] for m in mort),
        "equity": value - sum(m["balance"] for m in mort),
        "projection": real_estate_svc.equity_projection(value, appr, mort, int(p.get("years") or 30), year) if value > 0 else [],
        "paydown_vs_invest": [liab_svc.paydown_vs_invest(x, mmf, equity_ret, profile.effective_tax_rate) for x in liabs],
    }
    if p.get("new_home_price") is not None and value > 0:
        out["downsize"] = real_estate_svc.downsize(
            sale_price=value,
            mortgage=out["mortgage_balance"],
            cost_basis=float(p.get("cost_basis") or value),
            new_home_price=float(p["new_home_price"]),
            status=status,
            year=year,
            selling_cost_pct=p.get("selling_cost_pct"),
            other_income=float(p.get("other_income") or 0.0),
            old_upkeep_pct=profile.home_upkeep_pct,
            new_upkeep_pct=profile.home_upkeep_pct,
            state=getattr(profile, "state", None),
        )
    if p.get("target_col_index") is not None:
        out["relocation"] = real_estate_svc.cost_of_living(
            float(p.get("annual_spend") or profile.monthly_expenses_retirement * 12),
            float(p.get("current_col_index") or 100.0),
            float(p["target_col_index"]),
            float(p.get("other_income") or 0.0),
            status,
            year,
            getattr(profile, "state", None),
            p.get("target_state"),
        )
    return out


SCENARIO_METRICS = ("success_rate", "bridge_success_rate", "median_final_real", "p10_final_real")


def _scenario_profile(profile, overrides: dict):
    return SimpleNamespace(**(profile.to_dict() | overrides)) if overrides else profile


def _scenario_metrics(profile, overrides: dict, shock: float, n_sims: int) -> dict:
    p = _scenario_profile(profile, overrides)
    r = run_fire(p, n_sims=n_sims, detail=False, shock=shock)
    return {k: r.get(k) for k in SCENARIO_METRICS} | {"retire_age": p.target_retirement_age, "monthly_spend": p.monthly_expenses_retirement}


def scenario_compare(profile, saved: list, presets: list[dict], n_sims: int = 1500) -> dict:
    """Baseline vs saved scenarios vs presets, side by side, with differences against the baseline."""
    base = _scenario_metrics(profile, {}, 0.0, n_sims)
    items = [{"name": x.name, "kind": "saved", "overrides": x.overrides, "shock": x.shock} for x in saved] + [{**x, "kind": "preset"} for x in presets]
    rows = []
    for it in items:
        m = _scenario_metrics(profile, it["overrides"], it["shock"], n_sims)
        rows.append({**it, "metrics": m, "vs_base": scen_svc.diff(base, m, (*SCENARIO_METRICS, "retire_age", "monthly_spend"))})
    return {"base": base, "scenarios": rows, "n_sims": n_sims, "seed": 42}


def scenario_tornado(profile, n_sims: int = 800) -> dict:
    """Success-rate swing from moving each input down and up. Same seed, so only the input changes."""
    base = _scenario_metrics(profile, {}, 0.0, n_sims)["success_rate"]
    probes = [
        ("Retirement age", "target_retirement_age", profile.target_retirement_age - 2, profile.target_retirement_age + 2, "-2 yrs", "+2 yrs"),
        (
            "Retirement spending",
            "monthly_expenses_retirement",
            profile.monthly_expenses_retirement * 0.9,
            profile.monthly_expenses_retirement * 1.1,
            "-10%",
            "+10%",
        ),
        ("Monthly savings", "monthly_contribution", profile.monthly_contribution * 0.8, profile.monthly_contribution * 1.2, "-20%", "+20%"),
        ("Social Security", "social_security_monthly", profile.social_security_monthly * 0.77, profile.social_security_monthly * 1.1, "-23%", "+10%"),
        ("Health inflation", "health_inflation", profile.health_inflation + 0.02, max(profile.health_inflation - 0.02, 0.0), "+2 pts", "-2 pts"),
        ("Tax rate", "effective_tax_rate", profile.effective_tax_rate + 0.03, max(profile.effective_tax_rate - 0.03, 0.0), "+3 pts", "-3 pts"),
    ]
    results = []
    for label, field, a, b, la, lb in probes:
        lo = _scenario_metrics(profile, {field: a}, 0.0, n_sims)["success_rate"]
        hi = _scenario_metrics(profile, {field: b}, 0.0, n_sims)["success_rate"]
        results.append({"input": label, "field": field, "low_label": la, "high_label": lb, "low": lo, "high": hi})
    crash = _scenario_metrics(profile, {}, -0.30, n_sims)["success_rate"]
    results.append({"input": "First-year market", "field": "shock", "low_label": "-30%", "high_label": "as modelled", "low": crash, "high": base})
    return {"base_success": base, "bars": scen_svc.tornado(base, results), "n_sims": n_sims}


def scenario_solve(profile, kind: str, target: float | None = None, n_sims: int = 800) -> dict:
    """Reverse solver: the largest spend, smallest savings, or earliest retirement age that still reaches `target` success."""
    target = target or getattr(profile, "target_success_rate", 0.85) or 0.85

    def success(**o):
        return _scenario_metrics(profile, o, 0.0, n_sims)["success_rate"]

    out = {"kind": kind, "target_success": target, "n_sims": n_sims}
    if kind == "max_spend":
        top = max(profile.monthly_expenses_retirement * 3, 10_000)
        v = scen_svc.bisect(lambda x: success(monthly_expenses_retirement=x), 0.0, top, target, increasing=False)
        out |= {"value": v, "unit": "$/month in retirement (today's $)", "current": profile.monthly_expenses_retirement}
    elif kind == "required_savings":
        v = scen_svc.bisect(lambda x: success(monthly_contribution=x), 0.0, 25_000.0, target, increasing=True)
        out |= {"value": v, "unit": "$/month saved until retirement", "current": profile.monthly_contribution}
    elif kind == "earliest_age":
        v = next((float(a) for a in range(int(max(profile.current_age, 35)), 71) if success(target_retirement_age=float(a)) >= target), None)
        out |= {"value": v, "unit": "age", "current": profile.target_retirement_age}
    else:
        raise ValueError("kind must be max_spend, required_savings or earliest_age")
    if out["value"] is None:
        out["note"] = "Target not reachable inside the search range."
    return out


def withdrawal_plan(profile, strategies=wd.STRATEGIES, detail=True, retire_age: float | None = None) -> dict:
    s = db.session()
    accts = s.query(Account).all()
    retire = retire_age or profile.target_retirement_age
    events = [*s.query(PlannedEvent).all(), *pension_svc.virtual_events(s.query(Pension).all(), profile, retire)]
    inp = withdrawal_inputs(profile, accts, s.query(Liability).all(), events, retire)
    out = wd.compare(inp, tuple(strategies), detail=detail)
    out["retire_age"] = retire
    out["starting_balances"] = {"taxable": inp.taxable, "pretax": inp.pretax, "roth": inp.roth}
    out["aca_schedule"] = aca.subsidy_schedule(
        inp.household_size, aca.benchmark_annual([max(retire, 40.0)] * inp.household_size), medicaid_limit=inp.medicaid_limit
    )
    return out


def survivor_plan(profile, p: dict | None = None) -> dict:
    """If one spouse dies: single-filer tax on the same income, survivor Social Security, estate-tax exposure, beneficiary checklist and
    life/disability insurance gaps. Query inputs (all optional) override profile-derived defaults."""
    p = p or {}
    s = db.session()
    year = date.today().year
    d = survivor_svc.defaults()
    married = profile.spouse_age > 0
    summary = barbell_summary(s)
    spend = float(p["annual_spend"]) if p.get("annual_spend") is not None else (profile.monthly_expenses_retirement or profile.monthly_expenses_current) * 12
    out: dict = {"defaults": d, "married": married}
    if married:
        deceased = (p.get("deceased") or "SPOUSE").upper()
        me_ss, sp_ss = profile.social_security_monthly, profile.spouse_social_security_monthly
        me_claim, sp_claim = profile.ss_claim_age or 67, profile.spouse_ss_claim_age or 67
        gone_ss, gone_claim, keep_ss, keep_claim = (sp_ss, sp_claim, me_ss, me_claim) if deceased == "SPOUSE" else (me_ss, me_claim, sp_ss, sp_claim)
        sv = survivor_svc.survivor_social_security(gone_ss, keep_ss, gone_claim, keep_claim)
        draw = float(p["pretax_draw"]) if p.get("pretax_draw") is not None else max(spend - sv["household_before"] * 12, 0.0)
        out["deceased"] = deceased
        out["social_security"] = sv
        out["death_of_spouse"] = survivor_svc.death_of_spouse(
            year=year,
            spend=spend,
            ss_before_monthly=sv["household_before"],
            ss_after_monthly=sv["household_after"],
            other_ordinary=float(p.get("other_ordinary") or 0.0),
            pretax_draw=draw,
            spend_ratio=p.get("spend_ratio"),
        )
    out["estate"] = survivor_svc.estate_exposure(float(p["net_worth"]) if p.get("net_worth") is not None else summary["net_worth"], married)
    accts = [
        {"name": a.name, "bucket": a.tax_bucket, "owner": a.owner, "balance": sum(h.market_value for h in a.holdings)}
        for a in s.query(Account).order_by(Account.id)
    ]
    out["beneficiaries"] = survivor_svc.beneficiary_audit(accts)
    income = float(p["income"]) if p.get("income") is not None else max(profile.annual_income, profile.spouse_annual_income)
    liquid = float(p["liquid_assets"]) if p.get("liquid_assets") is not None else summary["totals"].get("dry_powder", 0.0)
    out["insurance"] = survivor_svc.insurance_gap(
        income=income,
        debts=summary["liabilities"],
        liquid_assets=liquid,
        existing_life=float(p.get("existing_life") or 0.0),
        group_disability_monthly=float(p.get("group_disability_monthly") or 0.0),
    )
    return out


def assumptions_view() -> dict:
    ov = stored_overrides()
    return {"assumptions": assumptions_svc.view(ov), "overridden": len(ov)}


def save_assumptions(changes: dict) -> dict:
    """Upsert overrides; a null value resets that key to its default. Raises ValueError on unknown keys or out-of-range values."""
    clean = assumptions_svc.validate(changes)
    s = db.session()
    for k, v in changes.items():
        row = s.get(AssumptionOverride, k)
        if v is None:
            if row:
                s.delete(row)
        elif row:
            row.value = clean[k]
        else:
            s.add(AssumptionOverride(key=k, value=clean[k]))
    s.commit()
    return assumptions_view()


def plan_health(profile, *, save: bool = False, n_sims: int = 1000) -> dict:
    """Score, explanation and diff against the last saved run. With save=True the current run becomes the new reference."""
    run = run_fire(profile, n_sims=n_sims, detail=True)
    ov = stored_overrides()
    cur = {"metrics": assumptions_svc.snapshot_metrics(run), "assumptions": assumptions_svc.effective(ov)}
    s = db.session()
    last = s.query(RunSnapshot).order_by(RunSnapshot.id.desc()).first()
    out = {
        "health": assumptions_svc.health(cur["metrics"], len(ov)),
        "metrics": cur["metrics"],
        "diff": assumptions_svc.diff(last.to_dict() if last else None, cur),
        "last_run_at": last.created_at.isoformat() if last else None,
    }
    if save:
        s.add(RunSnapshot(metrics=cur["metrics"], assumptions=cur["assumptions"]))
        s.commit()
    return out


def spending_goals_impact(profile, n_sims: int = 2000, seed: int = 42) -> dict:
    """Plan outcome with the enabled spending goals versus without them, on the same seeded return paths."""
    goals = db.session().query(SpendingGoal).filter_by(enabled=True).all()
    if not goals:
        return {"has_goals": False}
    without = run_fire(profile, n_sims=n_sims, seed=seed, detail=False, goals=[])
    with_ = run_fire(profile, n_sims=n_sims, seed=seed, detail=False, goals=goals)
    return {
        "has_goals": True,
        "success_rate_without": without["success_rate"],
        "success_rate_with": with_["success_rate"],
        "success_rate_change": with_["success_rate"] - without["success_rate"],
        "median_final_real_without": without.get("median_final_real"),
        "median_final_real_with": with_.get("median_final_real"),
        "target_success_rate": with_["target_success_rate"],
    }
