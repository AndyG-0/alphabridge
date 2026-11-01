"""Withdrawal-sequencing simulator: which account to draw from each retirement year, and what it costs in tax.

Deterministic, real (today's) dollars, no I/O. Taxes come from services/tax.py, ACA credits from services/aca.py,
so every year's draw is priced through the actual brackets, LTCG stacking, Social Security taxability and subsidy schedule.

Simplifications (also listed in the API response): constant real returns; tax tables held constant in real terms (indexing
roughly offsets inflation); a taxable-account withdrawal realizes gains at a fixed gain ratio; one filing status for all years;
pre-tax money is unavailable before `pretax_access_age` (no 72(t) modeling here, see services/early_access.py)."""

from dataclasses import dataclass, field

from services import aca
from services import tax as tax_svc

STRATEGIES = ("TAXABLE_FIRST", "PROPORTIONAL", "BRACKET_FILL", "TARGET_MAGI")
LABELS = {
    "TAXABLE_FIRST": "Taxable → pre-tax → Roth",
    "PROPORTIONAL": "Proportional across accounts",
    "BRACKET_FILL": "Fill a tax bracket with pre-tax first",
    "TARGET_MAGI": "Hold MAGI under the ACA cliff before Medicare",
}
MEDICARE_AGE = 65
_SOLVE_ITERS = 28


@dataclass
class Inputs:
    start_year: int
    start_age: float  # primary's age in the first simulated year
    end_age: float
    status: str = "SINGLE"
    state: str | None = None
    household_size: int = 1
    taxable: float = 0.0
    pretax: float = 0.0
    roth: float = 0.0
    gain_ratio: float = 0.3  # share of a taxable withdrawal that is realized gain
    real_return: float = 0.04
    spend: list[float] = field(default_factory=list)  # after-tax living + other costs by year (real), excluding the ACA premium
    ss: list[float] = field(default_factory=list)  # Social Security received by year
    ordinary_income: list[float] = field(default_factory=list)  # pensions, wages (taxable)
    other_cash: list[float] = field(default_factory=list)  # non-taxable inflows
    aca_benchmark: list[float] = field(default_factory=list)  # benchmark premium for people still under 65, by year (0 = no ACA)
    pretax_access_age: float = 59.5
    bracket_rate: float = 0.12  # BRACKET_FILL: fill ordinary income up to the top of this bracket
    magi_margin: float = 0.03  # TARGET_MAGI: stay this far under the cliff
    medicaid_limit: float | None = None


def _plan(order: list[tuple[str, float]], g: float, avail: dict[str, float]) -> dict[str, float]:
    """Greedy draw of `g` dollars across (pool, cap) stages in order."""
    out = {"taxable": 0.0, "pretax": 0.0, "roth": 0.0}
    left = g
    for pool, cap in order:
        room = max(min(avail[pool] - out[pool], cap), 0.0)
        take = min(room, left)
        out[pool] += take
        left -= take
        if left <= 1e-9:
            break
    return out


def _taxes(inp: Inputs, year: int, plan: dict[str, float], ss: float, ordinary_other: float) -> dict:
    gains = plan["taxable"] * inp.gain_ratio
    t = tax_svc.total_tax(
        ordinary=plan["pretax"] + ordinary_other,
        qualified=gains,
        social_security=ss,
        status=inp.status,
        year=year,
        state=inp.state,
    )
    # ACA MAGI counts all Social Security, taxable or not (IRC 36B(d)(2)(B))
    t["magi"] = t["agi"] + max(ss - t["taxable_social_security"], 0.0)
    return t


def _bracket_top(inp: Inputs, year: int) -> float:
    """Ordinary income (before the standard deduction) at the top of the chosen bracket."""
    br = tax_svc._brackets(inp.status, year)
    std = tax_svc.standard_deduction(inp.status, year)
    for i, (_, rate) in enumerate(br):
        if abs(rate - inp.bracket_rate) < 1e-9 and i + 1 < len(br):
            return br[i + 1][0] + std
    return br[-1][0] + std


def _order(strategy: str, inp: Inputs, avail: dict[str, float], g: float, year: int, ss: float, ordinary_other: float, aca_year: bool):
    """Stages for `strategy` at total draw `g`. BRACKET_FILL / TARGET_MAGI first take as much pre-tax as the limit allows."""
    after = [("taxable", float("inf")), ("roth", float("inf")), ("pretax", float("inf"))]
    if strategy == "TAXABLE_FIRST":
        return [("taxable", float("inf")), ("pretax", float("inf")), ("roth", float("inf"))]
    if strategy == "PROPORTIONAL":
        pools = {k: v for k, v in avail.items() if v > 0}
        total = sum(pools.values())
        return [(k, g * v / total) for k, v in pools.items()] + after if total > 0 else after
    if strategy == "BRACKET_FILL" or (strategy == "TARGET_MAGI" and not aca_year):
        # pre-tax up to the room left in the bracket (ordinary income incl. the taxable part of SS)
        def metric(x):
            plan = _plan([("pretax", x), *after], g, avail)
            t = _taxes(inp, year, plan, ss, ordinary_other)
            return plan["pretax"] + ordinary_other + t["taxable_social_security"]

        limit = _bracket_top(inp, year)
    else:  # TARGET_MAGI before Medicare

        def metric(x):
            plan = _plan([("pretax", x), *after], g, avail)
            return _taxes(inp, year, plan, ss, ordinary_other)["magi"]

        limit = aca.target_magi(inp.household_size, margin=inp.magi_margin)
    lo, hi = 0.0, min(g, avail["pretax"])
    if metric(hi) <= limit:
        return [("pretax", hi), *after]
    if metric(lo) > limit:
        return after  # already over the limit with no pre-tax draw; keep it to the cheaper pools
    for _ in range(_SOLVE_ITERS):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if metric(mid) <= limit else (lo, mid)
    return [("pretax", lo), *after]


def _solve_year(inp: Inputs, strategy: str, y: int, bal: dict[str, float], age: float) -> dict:
    year = inp.start_year + y
    ss = inp.ss[y] if y < len(inp.ss) else 0.0
    ordinary_other = inp.ordinary_income[y] if y < len(inp.ordinary_income) else 0.0
    other_cash = inp.other_cash[y] if y < len(inp.other_cash) else 0.0
    spend = inp.spend[y] if y < len(inp.spend) else 0.0
    bench = inp.aca_benchmark[y] if y < len(inp.aca_benchmark) else 0.0
    avail = {"taxable": bal["taxable"], "pretax": bal["pretax"] if age >= inp.pretax_access_age else 0.0, "roth": bal["roth"]}
    aca_year = bench > 0
    premium = 0.0
    t: dict = {}
    plan, shortfall = {"taxable": 0.0, "pretax": 0.0, "roth": 0.0}, 0.0
    for _ in range(3):  # the premium depends on MAGI, which depends on the draw that pays it
        need = spend + premium

        def net_cash(g):
            p = _plan(_order(strategy, inp, avail, g, year, ss, ordinary_other, aca_year), g, avail)
            tt = _taxes(inp, year, p, ss, ordinary_other)
            return p, tt, sum(p.values()) + ss + ordinary_other + other_cash - tt["total"]

        cap = sum(avail.values())
        if need <= 0 or net_cash(0.0)[2] >= need:
            plan, t, _ = net_cash(0.0)
        else:
            lo, hi = 0.0, cap
            if net_cash(hi)[2] < need:  # even drawing everything can't cover it
                plan, t, got = net_cash(hi)
                shortfall = need - got
            else:
                for _ in range(_SOLVE_ITERS):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if net_cash(mid)[2] < need else (lo, mid)
                plan, t, _ = net_cash(hi)
                shortfall = 0.0
        if not aca_year:
            break
        res = aca.premium(t["magi"], inp.household_size, bench, medicaid_limit=inp.medicaid_limit)
        if abs(res["net"] - premium) < 1.0:
            premium = res["net"]
            break
        premium = res["net"]
    aca_res = aca.premium(t["magi"], inp.household_size, bench, medicaid_limit=inp.medicaid_limit) if aca_year else None
    return {
        "year": year,
        "age": round(age, 1),
        "draw_taxable": plan["taxable"],
        "draw_pretax": plan["pretax"],
        "draw_roth": plan["roth"],
        "social_security": ss,
        "magi": t["magi"],
        "agi": t["agi"],
        "ordinary_income": plan["pretax"] + ordinary_other,
        "taxable_social_security": t["taxable_social_security"],
        "federal_tax": t["federal"],
        "state_tax": t["state"],
        "tax": t["total"],
        "marginal_rate": t["marginal_rate"],
        "aca_premium": premium if aca_year else 0.0,
        "aca_over_cliff": bool(aca_res and aca_res["over_cliff"]),
        "shortfall": shortfall,
    }


def simulate(inp: Inputs, strategy: str) -> dict:
    """Year-by-year table for one strategy."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    bal = {"taxable": inp.taxable, "pretax": inp.pretax, "roth": inp.roth}
    rows = []
    years = int(inp.end_age - inp.start_age)
    for y in range(max(years, 0)):
        age = inp.start_age + y
        row = _solve_year(inp, strategy, y, bal, age)
        bal["taxable"] -= row["draw_taxable"]
        bal["pretax"] -= row["draw_pretax"]
        bal["roth"] -= row["draw_roth"]
        for k in bal:
            bal[k] = max(bal[k], 0.0) * (1 + inp.real_return)
        row["balances"] = dict(bal.items())
        rows.append(row)
    return summarize(strategy, rows, bal)


def summarize(strategy: str, rows: list[dict], bal: dict[str, float]) -> dict:
    last_marginal = rows[-1]["marginal_rate"] if rows else 0.0
    taxes = sum(r["tax"] for r in rows)
    premiums = sum(r["aca_premium"] for r in rows)
    ending = sum(bal.values())
    return {
        "strategy": strategy,
        "label": LABELS.get(strategy, strategy),
        "years": rows,
        "lifetime_tax": taxes,
        "lifetime_aca_premiums": premiums,
        "lifetime_cost": taxes + premiums,
        "shortfall_years": sum(1 for r in rows if r["shortfall"] > 1.0),
        "total_shortfall": sum(r["shortfall"] for r in rows),
        "ending_balance": ending,
        "ending_after_tax": bal["taxable"] + bal["roth"] + bal["pretax"] * (1 - last_marginal),
        "years_over_aca_cliff": sum(1 for r in rows if r["aca_over_cliff"]),
    }


def compare(inp: Inputs, strategies: tuple[str, ...] = STRATEGIES, detail: bool = True) -> dict:
    """Run every strategy; rank by (fewest shortfall years, lowest lifetime tax + premiums, highest ending after-tax wealth)."""
    results = [simulate(inp, s) for s in strategies]
    ranked = sorted(results, key=lambda r: (r["shortfall_years"], round(r["lifetime_cost"]), -r["ending_after_tax"]))
    best = ranked[0]["strategy"]
    base = next((r for r in results if r["strategy"] == "TAXABLE_FIRST"), results[0])
    out = []
    for r in results:
        row = {k: v for k, v in r.items() if k != "years" or detail}
        row["vs_taxable_first"] = r["lifetime_cost"] - base["lifetime_cost"]
        out.append(row)
    return {
        "best": best,
        "strategies": out,
        "assumptions": [
            "Real (today's) dollars with constant real returns.",
            "Tax tables held constant in real terms; filing status unchanged all years.",
            "Taxable withdrawals realize gains at the current gain ratio.",
            "ACA MAGI includes all Social Security, taxable or not.",
            "Pre-tax money is unavailable before the penalty-free access age; shortfalls show where that binds.",
        ],
        "rules_year": tax_svc.rules_year(inp.start_year),
        "aca_rules_year": aca.RULES_YEAR,
        "aca_enhanced": aca.ENHANCED,
    }
