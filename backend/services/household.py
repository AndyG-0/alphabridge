"""Household cash flows for the retirement simulation. Pure functions, no I/O, no LLM.

Everything is indexed by simulation year y (y = 0 is the current year, the primary is current_age + y)
and is in today's dollars unless the name says nominal. The planner turns these into FireInputs vectors.
"""

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from services import aca, healthcare, income_streams, state_rules
from services import coverage as coverage_svc
from services import liabilities as liab_svc
from services import social_security as ss_svc
from services import spending as spending_svc
from services import tax as tax_svc

MEDICARE_AGE = 65
UNLOCK_AGE = 59.5
# Health care outpaces general inflation for this many years, then tracks it (excess growth can't compound forever)
HEALTH_EXCESS_YEARS = 20


def ss_factor(claim_age: float) -> float:
    """Benefit multiple vs. the age-67 amount (the profile's benefit is entered "at 67")."""
    return ss_svc.adjustment(claim_age, 67.0)


def year_index(years_from_now: float) -> int:
    """First simulation year in which something `years_from_now` away is in effect."""
    return max(math.ceil(years_from_now - 1e-9), 0)


@dataclass
class Person:
    key: str  # SELF | SPOUSE
    name: str
    age_now: float
    retire_age: float  # in their own age
    ss_monthly_67: float
    ss_claim_age: float
    income: float

    def years_until(self, own_age: float) -> float:
        return own_age - self.age_now

    def age_in(self, y: int) -> float:
        return self.age_now + y


def people(profile, retire_age: float | None = None) -> list[Person]:
    """The primary and (if a spouse birth date is set) the spouse. With no separate spouse target the
    spouse retires the same day as the primary."""
    r = profile.target_retirement_age if retire_age is None else retire_age
    out = [
        Person(
            "SELF",
            profile.name or "You",
            profile.current_age,
            r,
            profile.social_security_monthly,
            getattr(profile, "ss_claim_age", 67) or 67,
            profile.annual_income,
        )
    ]
    if profile.spouse_age > 0:
        sp_r = profile.spouse_target_retirement_age or profile.spouse_age + (r - profile.current_age)
        out.append(
            Person(
                "SPOUSE",
                profile.spouse_name or "Spouse",
                profile.spouse_age,
                sp_r,
                profile.spouse_social_security_monthly,
                getattr(profile, "spouse_ss_claim_age", 67) or 67,
                profile.spouse_annual_income,
            )
        )
    return out


def event_years(ev, this_year: int, years: int) -> list[int]:
    """Simulation years in which a planned event occurs (PENSION: every year it pays)."""
    end = ev.repeat_until_year or (this_year + years - 1)
    if ev.kind == "PENSION" or ev.kind in income_streams.RECURRING:
        return [y for y in range(max(ev.start_year - this_year, 0), years) if this_year + y <= end]
    step = ev.repeat_every_years or 0
    cal = list(range(ev.start_year, end + 1, step)) if step > 0 else [ev.start_year]
    return [c - this_year for c in cal if 0 <= c - this_year < years]


def loan_payment(principal: float, apr: float, months: int) -> float:
    if principal <= 0 or months <= 0:
        return 0.0
    r = apr / 12
    return principal / months if r == 0 else principal * r / (1 - (1 + r) ** -months)


@dataclass
class Flows:
    years: int
    retire_y: int
    extra_spend: np.ndarray  # health, purchases, upkeep, escrow, LTC (today's $, already adjusted for health inflation)
    income: np.ndarray  # inflows, pensions, a still-working spouse's take-home pay (today's $)
    debt_nominal: np.ndarray  # fixed loan payments incl. extra principal and financed purchases
    contrib_bridge: np.ndarray
    contrib_pretax: np.ndarray
    contrib_pretax_spouse: np.ndarray
    ss_self: tuple[float, float]  # (annual today's $, start age in primary terms)
    ss_spouse: tuple[float, float]
    health: list[dict] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)  # per-category arrays for the UI


def build_flows(
    profile,
    liabilities,
    events,
    *,
    retire_age: float,
    years: int,
    inflation: float,
    taxable_now: float = 0.0,
    real_return_taxable: float = 0.04,
    gain_ratio: float = 0.3,
    today: date | None = None,
    coverage_options: list | None = None,
) -> Flows:
    """Year-by-year household cash flows for one candidate retirement age."""
    today = today or date.today()
    ppl = people(profile, retire_age)
    me, sp = ppl[0], (ppl[1] if len(ppl) > 1 else None)
    retire_y = year_index(retire_age - me.age_now)
    sp_retire_y = year_index(sp.years_until(sp.retire_age)) if sp else retire_y
    hi = getattr(profile, "health_inflation", 0.05)
    tax = profile.effective_tax_rate

    def health_adj(y):  # the sim inflates at general inflation; health costs grow faster, for a while
        return ((1 + hi) / (1 + inflation)) ** min(y, HEALTH_EXCESS_YEARS)

    # --- contributions, split by who earns them; each stops at that person's retirement
    annual = profile.monthly_contribution * 12
    total_inc = me.income + (sp.income if sp else 0)
    sp_share = (sp.income / total_inc) if (sp and total_inc > 0) else 0.0
    c_b, c_p, c_ps = np.zeros(years), np.zeros(years), np.zeros(years)
    for y in range(years):
        mine = annual * (1 - sp_share) if y < retire_y else 0.0
        theirs = annual * sp_share if (sp and y < sp_retire_y) else 0.0
        c_b[y] = 0.4 * (mine + theirs)
        c_p[y] = 0.6 * mine
        c_ps[y] = 0.6 * theirs

    # --- events: purchases, inflows, pensions, home sale
    this_year = today.year
    purchases, inflows, pensions = np.zeros(years), np.zeros(years), np.zeros(years)
    debt = np.zeros(years)
    home_sale_y = years
    stream_parts: list[list[dict]] = [[] for _ in range(years)]
    for ev in events:
        for y in event_years(ev, this_year, years):
            if ev.kind == "PENSION":
                pensions[y] += ev.amount * 12
            elif ev.kind in income_streams.STREAM_KINDS:
                paid = max(this_year + y - ev.start_year, 0)
                stream_parts[y].append(income_streams.components(ev.kind, ev.amount, getattr(ev, "basis", 0.0) or 0.0, paid))
            elif ev.kind == "INFLOW":
                inflows[y] += ev.amount
                if ev.is_home_sale:
                    home_sale_y = min(home_sale_y, y)
            elif ev.financed:
                down = min(ev.down_payment, ev.amount)
                purchases[y] += down
                principal = (ev.amount - down) * (1 + inflation) ** y  # loan is taken in future dollars
                pay = loan_payment(principal, ev.loan_apr, ev.loan_term_months)
                for m in range(ev.loan_term_months):
                    yy = y + (m // 12)
                    if yy < years:
                        debt[yy] += pay
            else:
                purchases[y] += ev.amount

    # --- taxed income streams (P11): net of the incremental tax over the pension income already in that year
    stream_ordinary = np.zeros(years)
    status_ = getattr(profile, "tax_filing_status", "SINGLE")
    for y in range(years):
        if stream_parts[y]:
            r = income_streams.after_tax(stream_parts[y], pensions[y], status_, this_year + y, getattr(profile, "state", None))
            inflows[y] += r["net"]
            stream_ordinary[y] = r["ordinary"] + r["qualified"]

    # --- existing debts (extra principal stops at retirement unless set to run to payoff); a home sale ends the mortgage
    stop_m = max(round((retire_age - me.age_now) * 12), 0)
    for liab in liabilities:
        d = liab_svc.debt_service_by_year([liab], years, today, extra_stop_month=stop_m)
        if liab.kind == "MORTGAGE":
            d[home_sale_y:] = 0
        debt += d
    escrow = liab_svc.escrow_monthly(liabilities) * 12

    # --- spouse still working after the primary retires: their take-home covers part of the spending
    wages = np.zeros(years)
    if sp and sp_retire_y > retire_y:
        take_home = getattr(profile, "spouse_take_home_monthly", 0) or max(sp.income * (1 - tax) / 12 - annual * sp_share / 12, 0)
        wages[retire_y:sp_retire_y] = take_home * 12

    # --- Social Security, adjusted for claiming age, start expressed in the primary's age
    ss_self = (me.ss_monthly_67 * 12 * ss_factor(me.ss_claim_age), me.ss_claim_age)
    ss_sp = (0.0, 67.0)
    if sp:
        ss_sp = (sp.ss_monthly_67 * 12 * ss_factor(sp.ss_claim_age), me.age_now + sp.years_until(sp.ss_claim_age))

    # --- home upkeep + escrow in retirement (before that they're inside current expenses)
    upkeep, escrow_v = np.zeros(years), np.zeros(years)
    for y in range(retire_y, min(home_sale_y, years)):
        upkeep[y] = profile.home_value * profile.home_upkeep_pct
        escrow_v[y] = escrow

    # --- long-term care, per person
    ltc = np.zeros(years)
    if profile.ltc_years > 0:
        for p in ppl:
            for y in range(years):
                if profile.ltc_start_age <= p.age_in(y) < profile.ltc_start_age + profile.ltc_years:
                    ltc[y] += profile.ltc_annual  # today's $, grows with general inflation

    # --- health care: employer plan while anyone works; then ACA (with subsidy) before 65, Medicare after
    health = []
    health_v = np.zeros(years)
    st = state_rules.rules_for(getattr(profile, "state", "AZ"))
    ce = state_rules.engagement()
    meets_ce = bool(getattr(profile, "meets_community_engagement", False))
    medicaid_limit = st["adult_limit_fpl"] if st["medicaid_expansion"] else None
    tax_bal = taxable_now
    base_spend = profile.monthly_expenses_retirement * 12
    smodel = spending_svc.load(getattr(profile, "spending_model", None))
    spend_adj = np.zeros(years)  # smile and category drift versus the flat base, today's $ (zero with the default model)
    if not spending_svc.is_default(smodel):
        for y in range(retire_y, years):
            spend_adj[y] = base_spend * (spending_svc.multiplier(smodel, me.age_in(y), y) - 1.0)
    prev_premium = 0.0
    cov_choice = getattr(profile, "coverage_choice", None) or {}
    cov_opts = {o.id: o for o in (coverage_options or [])}
    for y in range(years):
        working = y < retire_y or (sp is not None and y < sp_retire_y)
        if y < retire_y:
            tax_bal = tax_bal * (1 + real_return_taxable) + c_b[y] - purchases[y]
            health.append({"year": this_year + y, "coverage": "EMPLOYER", "total": 0.0})
            continue
        income_y = inflows[y] + pensions[y] + wages[y]
        ss_y = (ss_self[0] if me.age_in(y) >= ss_self[1] else 0.0) + (ss_sp[0] if me.age_in(y) >= ss_sp[1] else 0.0)
        other = purchases[y] + upkeep[y] + escrow_v[y] + ltc[y] + debt[y] / (1 + inflation) ** y
        under = [p for p in ppl if p.age_in(y) < MEDICARE_AGE]
        over = [p for p in ppl if p.age_in(y) >= MEDICARE_AGE]
        row = {"year": this_year + y, "ages": {p.key: round(p.age_in(y), 1) for p in ppl}}
        total = 0.0
        if working:
            row.update(coverage="EMPLOYER", total=0.0)
        else:
            override = getattr(profile, "aca_benchmark_premium_monthly", 0) or 0
            # a person with an eligible chosen plan leaves ACA / flat Medicare; an ineligible choice falls back with a note
            chosen: dict[str, object] = {}
            notes: list[str] = []
            for p in ppl:
                opt = cov_opts.get(cov_choice.get(p.key) or 0)
                if opt is None:
                    continue
                age = p.age_in(y)
                right_stage = (opt.category in coverage_svc.MEDICARE_CATEGORIES) == (age >= MEDICARE_AGE)
                if opt.category != "DRUG" and right_stage and coverage_svc.eligible(opt, age, p.key):
                    chosen[p.key] = opt
                else:
                    notes.append(f"{opt.name} not available to {p.name} at {age:.0f}; priced as {'Medicare' if age >= MEDICARE_AGE else 'ACA'}")
            plan_cost_by_key: dict[str, float] = {}
            for k, opt in chosen.items():
                n = sum(1 for o in chosen.values() if o.id == opt.id)
                plan_cost_by_key[k] = coverage_svc.annual_cost(opt, this_year + y, n, cov_opts.get(opt.drug_option_id or 0))
            aca_under = [p for p in under if p.key not in chosen]
            plan_cost = sum(plan_cost_by_key[p.key] for p in under if p.key in chosen)
            bench = (override * 12 * len(aca_under) / len(ppl)) if override else (aca.benchmark_annual([p.age_in(y) for p in aca_under]) if aca_under else 0.0)
            magi = 0.0
            for _ in range(3):  # premium depends on MAGI, which depends on the withdrawal that pays the premium
                gross = (base_spend + spend_adj[y] + other + prev_premium) / max(1 - tax, 0.05)
                draw = max(gross - ss_y - income_y, 0.0)
                from_tax = min(max(tax_bal, 0.0), draw)
                other_income = from_tax * gain_ratio + (draw - from_tax) + pensions[y] + stream_ordinary[y] + wages[y] / max(1 - tax, 0.05)
                ss_taxable = tax_svc.taxable_social_security(ss_y, other_income, getattr(profile, "tax_filing_status", "SINGLE"), this_year + y)
                magi = other_income + ss_taxable
                res = (
                    aca.premium(
                        magi,
                        len(ppl),
                        bench,
                        medicaid_limit=medicaid_limit,
                        medicaid_blocked=this_year + y >= ce["start_year"] and not meets_ce,
                    )
                    if aca_under
                    else {
                        "net": 0.0,
                        "benchmark": 0.0,
                        "credit": 0.0,
                        "fpl_ratio": None,
                        "medicaid": False,
                        "over_cliff": False,
                        "coverage_gap": False,
                        "engagement_blocked": False,
                    }
                )
                prev_premium = res["net"] + plan_cost
            dental = profile.dental_vision_monthly * 12 * len(ppl)
            oop = profile.health_oop_annual * len(under)
            status = getattr(profile, "tax_filing_status", "SINGLE")
            medicare = 0.0
            for p in over:
                if p.key in chosen:  # Medicare Advantage / Medigap: plan premium (with its drug add-on) + Part B if required + Part D IRMAA
                    i = tax_svc.irmaa(magi, status, this_year + y)
                    medicare += 12 * ((i["part_b_total_monthly"] if chosen[p.key].requires_part_b_premium else 0.0) + i["part_d_surcharge_monthly"])
                    medicare += plan_cost_by_key[p.key]
                else:
                    medicare += profile.medicare_monthly_per_person * 12 + healthcare.irmaa_surcharge_monthly(magi, status, this_year + y) * 12
            adj = health_adj(y)
            total = (res["net"] + plan_cost + dental + oop + medicare) * adj
            cliff = aca.cliff_magi(len(ppl)) if under else None
            row.update(
                coverage="ACA" if under and not over else "MEDICARE" if not under else "ACA+MEDICARE",
                coverage_plans=[chosen[p.key].name for p in ppl if p.key in chosen],
                coverage_note="; ".join(notes),
                plan_cost=plan_cost * adj,
                aca_benchmark=res["benchmark"] * adj,
                aca_credit=res["credit"] * adj,
                aca_net=res["net"] * adj,
                medicaid=res["medicaid"],
                medicaid_agency=st["agency"],
                coverage_gap=res["coverage_gap"],
                engagement_blocked=res["engagement_blocked"],
                engagement_required=this_year + y >= ce["start_year"] and res["medicaid"],
                over_cliff=res["over_cliff"],
                magi_est=magi,
                cliff_magi=cliff,
                fpl_ratio=res["fpl_ratio"],
                dental_vision=dental * adj,
                out_of_pocket=oop * adj,
                medicare=medicare * adj,
                total=total,
            )
            health_v[y] = total
        draw_total = max((base_spend + spend_adj[y] + other + total) / max(1 - tax, 0.05) - ss_y - income_y, 0.0)
        tax_bal -= min(max(tax_bal, 0.0), draw_total)
        tax_bal = tax_bal * (1 + real_return_taxable)
        health.append(row)

    extra = purchases + upkeep + escrow_v + ltc + health_v + spend_adj
    return Flows(
        years=years,
        retire_y=retire_y,
        extra_spend=extra,
        income=inflows + pensions + wages,
        debt_nominal=debt,
        contrib_bridge=c_b,
        contrib_pretax=c_p,
        contrib_pretax_spouse=c_ps,
        ss_self=ss_self,
        ss_spouse=ss_sp,
        health=health,
        breakdown={
            "health": health_v,
            "spending_adjustment": spend_adj,
            "purchases": purchases,
            "home_upkeep": upkeep,
            "escrow": escrow_v,
            "ltc": ltc,
            "inflows": inflows,
            "pensions": pensions,
            "spouse_wages": wages,
            "income_streams": stream_ordinary,
        },
    )


def payoff_schedule(profile, liabilities, *, retire_age: float, today: date | None = None) -> list[dict]:
    """When each debt is gone, with both people's ages then. `ongoing` = the payment never retires it."""
    today = today or date.today()
    ppl = people(profile, retire_age)
    me = ppl[0]
    stop_m = max(round((retire_age - me.age_now) * 12), 0)
    out = []
    for liab in liabilities:
        if liab.balance <= 0:
            continue
        sched = liab_svc.monthly_schedule(
            liab, liab_svc.HORIZON_MONTHS, stop_m if getattr(liab, "extra_payment_until", "RETIREMENT") == "RETIREMENT" else None, today
        )
        n = int(np.count_nonzero(sched))
        ongoing = n >= liab_svc.HORIZON_MONTHS
        yy, mm = divmod(today.month - 1 + n, 12)
        out.append(
            {
                "id": liab.id,
                "name": liab.name,
                "kind": liab.kind,
                "owner": liab.owner,
                "balance": liab.balance,
                "monthly_payment": liab.monthly_payment,
                "months": n,
                "payoff_year": None if ongoing else today.year + yy,
                "payoff_month": None if ongoing else mm + 1,
                "ages": {p.key: round(p.age_now + n / 12, 1) for p in ppl},
                "paid_before_retirement": (not ongoing) and n <= stop_m,
                "ongoing": ongoing,
            }
        )
    return sorted(out, key=lambda d: d["months"])


def timeline(profile, liabilities, events, *, retire_age: float, today: date | None = None) -> list[dict]:
    """Milestones with both people's ages and the calendar year, sorted by date."""
    today = today or date.today()
    ppl = people(profile, retire_age)
    me = ppl[0]
    out = []

    def add(years_from_now: float, label: str, kind: str, who: str = "JOINT"):
        if years_from_now < -0.01:
            return
        out.append(
            {
                "year": today.year + int(years_from_now + (today.month - 1) / 12),
                "years_from_now": round(years_from_now, 2),
                "ages": {p.key: round(p.age_now + years_from_now, 1) for p in ppl},
                "label": label,
                "kind": kind,
                "who": who,
            }
        )

    sp = ppl[1] if len(ppl) > 1 else None
    if sp and abs(sp.years_until(sp.retire_age) - me.years_until(me.retire_age)) < 0.05:
        add(me.years_until(me.retire_age), "You both retire", "RETIRE")
    else:
        add(me.years_until(me.retire_age), f"{me.name} retires", "RETIRE", "SELF")
        if sp:
            add(sp.years_until(sp.retire_age), f"{sp.name} retires", "RETIRE", "SPOUSE")
    for p in ppl:
        add(p.years_until(UNLOCK_AGE), f"{p.name}'s 401(k)/IRA unlocks (59½)", "UNLOCK", p.key)
        add(p.years_until(MEDICARE_AGE), f"{p.name} starts Medicare", "MEDICARE", p.key)
        add(
            p.years_until(p.ss_claim_age),
            f"{p.name} claims Social Security at {p.ss_claim_age:g} ({ss_factor(p.ss_claim_age):.0%} of age-67 benefit)",
            "SS",
            p.key,
        )
        if profile.ltc_years > 0:
            add(p.years_until(profile.ltc_start_age), f"{p.name}: long-term-care cost assumed ({profile.ltc_years:g} yrs)", "LTC", p.key)
    stop_m = max(round((retire_age - me.age_now) * 12), 0)
    for liab in liabilities:
        if liab.balance <= 0:
            continue
        sched = liab_svc.monthly_schedule(
            liab, liab_svc.HORIZON_MONTHS, stop_m if getattr(liab, "extra_payment_until", "RETIREMENT") == "RETIREMENT" else None, today
        )
        n = int(np.count_nonzero(sched))
        if n < liab_svc.HORIZON_MONTHS:
            add(n / 12, f"{liab.name} paid off", "DEBT", liab.owner)
    for ev in events:
        for y in event_years(ev, today.year, 60)[: 1 if ev.kind in ("PENSION", *income_streams.RECURRING) else 20]:
            label = {
                "PENSION": f"{ev.name} begins (${ev.amount:,.0f}/mo)",
                "ANNUITY": f"{ev.name} begins (${ev.amount:,.0f}/mo)",
                "INFLOW": f"{ev.name} (+${ev.amount:,.0f})",
            }.get(ev.kind, f"{ev.name} (${ev.amount:,.0f}{', financed' if ev.financed else ''})")
            add(max(y - (today.month - 1) / 12, 0), label, ev.kind, ev.owner)
    return sorted(out, key=lambda m: m["years_from_now"])
